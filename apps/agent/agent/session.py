"""LiveKit Agents entrypoint for the voice loop.

The worker is dispatched into a room by LiveKit, joins it, builds an
:class:`AgentSession` with the configured realtime model, registers
the tools from :mod:`core.tools`, and runs until the room closes.

Boundaries:

- This module imports `core.realtime` for the model factory,
  `core.config` / `core.observability` for settings + logging, and
  `core.tools` for the tool registry. It is the *only* place LiveKit-
  specific wiring (`Agent`, `AgentSession`, `JobContext`, the
  ``function_tools_executed`` event, the data-channel topic) lives in
  the agent worker. Business logic for the tools themselves stays in
  `core.tools`.
- Tool calls are forwarded to the frontend on the ``lk.tool-calls``
  topic — distinct from the existing ``lk.transcription`` topic — so
  the transcript view can render them as a third message type without
  parsing free-form text.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import structlog
from core import conversations as core_conversations
from core import preferences as core_preferences
from core.auth import User
from core.config import Settings, get_settings
from core.observability import (
    bind as bind_log_context,
)
from core.observability import (
    handle_metrics_event,
    setup_logging,
)
from core.observability import (
    unbind as unbind_log_context,
)
from core.realtime import create_realtime_model
from core.tools import (
    ToolContext as DomainToolContext,
)
from core.tools import (
    all_tools,
    dispatch,
)
from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions
from livekit.agents.llm import function_tool
from livekit.agents.voice.events import (
    ConversationItemAddedEvent,
    FunctionToolsExecutedEvent,
)

# The data-channel topic the agent uses to forward tool-call events
# to the frontend. Distinct from `lk.transcription` (the existing
# transcript topic) so the web client can render tool calls as a
# third message type without parsing free-form text.
TOOL_CALLS_TOPIC = "lk.tool-calls"

# System prompt for the tracer slice. Issue 06 adds tool-availability
# language so the realtime model knows it can call `get_current_time`
# and `get_weather`. Issue 07 extends the prompt with the structured-
# preferences tools so the agent saves stated facts and consults them
# before answering personal questions. Subsequent issues move this
# into a versioned prompt file.
SYSTEM_PROMPT = (
    "You are a helpful conversational assistant. "
    "Keep responses brief and natural for a spoken conversation. "
    "You have access to tools to look up the current time and the weather. "
    "Use them when the user asks about time or weather. "
    "\n\nMemory model — two distinct paths, do not confuse them:\n"
    "1. STRUCTURED PREFERENCES (set_preference / get_preference). "
    "Use these for any single-valued, named fact about the user — "
    "favorite color, preferred name, language, dietary needs, time zone, "
    "and similar. The key is a short snake_case identifier; the value is "
    "what the user said. When the user STATES one of these, call "
    "set_preference. When the user ASKS about one of these, prefer the "
    "'Known facts about the user' block in this prompt (it is preloaded "
    "from storage at session start); call get_preference only if the "
    "fact is not in that block.\n"
    "2. EPISODIC MEMORY (remember / recall). Use these for fuzzy facts "
    "that don't fit a single key — interests, relationships, ongoing "
    "projects, things the user is learning, anecdotes. Do NOT use "
    "remember/recall for anything that is already a structured "
    "preference; pick the structured path first whenever the fact has "
    "a natural snake_case key."
)


@dataclass(slots=True)
class _SessionDeps:
    """Per-session bindings the agent worker needs to pass into tool dispatch.

    Held as a small dataclass rather than module-level globals so a
    fresh session can be started in tests without leaking state from a
    previous one.
    """

    user: User
    log: Any  # structlog BoundLogger; kept loose to avoid a hard dep here.
    supabase_access_token: str | None = None


def _resolve_user_from_participant(participant: Any) -> User:
    """Reconstruct the :class:`User` from the connecting participant.

    The API minted the token with the Supabase user id as the
    participant identity (see :mod:`core.livekit`). The `name` field
    carries the email. We deliberately do not re-verify the JWT here:
    LiveKit has already verified it on join, and the worker's job is
    to act on a participant that has already been admitted.

    Note: the agent's own ``ctx.token_claims()`` returns the agent's
    auto-generated identity (e.g. ``agent-AJ_…``), which is not a UUID
    — that's why we read from the remote participant instead.
    """
    identity = participant.identity
    name = getattr(participant, "name", "") or ""
    return User(id=UUID(identity), email=name)


def _make_livekit_tool(schema_name: str, deps: _SessionDeps) -> Any:
    """Wrap a registered core tool as a LiveKit ``RawFunctionTool``.

    LiveKit Agents accepts tools through the `Agent(tools=[...])`
    constructor; each tool needs a callable plus a schema. We build a
    thin closure that delegates to :func:`core.tools.dispatch` so the
    error trapping, structured logging, and context injection live in
    one place (the registry) regardless of the transport.
    """
    from core.tools.registry import get_tool

    schema = get_tool(schema_name)
    if schema is None:
        raise RuntimeError(f"tool {schema_name!r} is not registered")

    raw_schema: dict[str, Any] = {
        "name": schema.name,
        "description": schema.description,
        "parameters": schema.parameters,
    }

    @function_tool(raw_schema=raw_schema)
    async def _invoke(raw_arguments: dict[str, Any], **_: Any) -> str:
        domain_ctx = DomainToolContext(
            user=deps.user,
            log=deps.log,
            supabase_access_token=deps.supabase_access_token,
        )
        result = await dispatch(schema_name, raw_arguments, domain_ctx)
        # The realtime model expects a string result. JSON-encode
        # mappings (errors, structured outputs) so the model gets a
        # parseable payload it can verbalise.
        if isinstance(result, str):
            return result
        return json.dumps(result)

    return _invoke


def build_agent(
    deps: _SessionDeps | None = None,
    *,
    instructions: str | None = None,
) -> Agent:
    """Construct the :class:`Agent` with the system prompt and tools.

    When ``deps`` is omitted, the agent is built without tools (the
    shape the issue-05 unit tests still rely on). The session
    entrypoint always passes ``deps`` so the live agent has tools.

    ``instructions`` overrides the default :data:`SYSTEM_PROMPT` —
    issue 10 uses this seam to inject a "call the user X" line built
    by :func:`build_system_prompt` from their stored preferences.
    """
    prompt = instructions if instructions is not None else SYSTEM_PROMPT
    if deps is None:
        return Agent(instructions=prompt)

    tools = [_make_livekit_tool(schema.name, deps) for schema in all_tools()]
    return Agent(instructions=prompt, tools=list(tools))


def build_session(
    settings: Settings | None = None,
    *,
    voice: str | None = None,
) -> AgentSession[None]:
    """Construct the :class:`AgentSession` with the realtime model.

    Factored out so tests can build a session without dispatching a
    real LiveKit job, and so the realtime model factory remains the
    only seam for swapping providers.

    ``voice`` is the OpenAI Realtime voice id read at session start
    from the user's stored preferences (issue 10). When ``None`` the
    plugin's default voice is used.
    """
    settings = settings or get_settings()
    model = create_realtime_model(settings, voice=voice)
    return AgentSession[None](llm=model)


def _load_user_preferences(
    user: User,
    supabase_token: str | None,
    log: Any,
) -> tuple[str | None, str | None, dict[str, Any]]:
    """Read all stored preferences for the session start.

    Returns ``(preferred_name, voice, all_prefs)``. Any of the first
    two may be ``None``; ``all_prefs`` is the full row map so the
    system prompt can list every stored preference as a known fact.
    Without this preload the model has to call ``get_preference`` to
    recall anything other than name/voice — which it does
    inconsistently, so cross-session recall feels broken.

    When the access token is missing or the read fails, returns
    ``(None, None, {})`` and the session falls back to the unbranded
    prompt and the default voice. Failure to read preferences must
    not crash the voice loop — same degradation principle as the rest
    of the session bootstrap.
    """
    if supabase_token is None:
        return (None, None, {})
    try:
        rows = core_preferences.list(user, access_token=supabase_token)
    except Exception as exc:  # noqa: BLE001 — degrade rather than crash
        log.warning("agent.preferences.read_failed", error=str(exc))
        return (None, None, {})
    raw_name = rows.get(core_preferences.PREFERRED_NAME_KEY)
    raw_voice = rows.get(core_preferences.VOICE_KEY)
    name: str | None = None
    voice: str | None = None
    if isinstance(raw_name, str) and raw_name.strip():
        name = raw_name.strip()
    if isinstance(raw_voice, str) and raw_voice in core_preferences.OPENAI_REALTIME_VOICES:
        voice = raw_voice
    log.info(
        "agent.preferences.loaded",
        count=len(rows),
        keys=sorted(rows.keys()),
    )
    return (name, voice, dict(rows))


def build_system_prompt(
    preferred_name: str | None,
    preferences: dict[str, Any] | None = None,
) -> str:
    """Return the agent's system prompt, optionally personalised.

    Three layers stack onto :data:`SYSTEM_PROMPT`:

    * ``preferred_name`` — instructs the model to address the user by
      that name.
    * ``preferences`` — every other stored preference is listed as a
      known fact so the model can verbalise them directly without
      having to call ``get_preference``. ``preferred_name`` and
      ``voice`` are excluded (the former is already handled above; the
      latter is a session config, not a fact about the user).

    Pure function so tests can assert the wiring without spinning up
    a LiveKit session.
    """
    prompt = SYSTEM_PROMPT
    if preferred_name:
        prompt += f" The user prefers to be called {preferred_name}."

    facts: list[str] = []
    if preferences:
        excluded = {core_preferences.PREFERRED_NAME_KEY, core_preferences.VOICE_KEY}
        for key, value in sorted(preferences.items()):
            if key in excluded:
                continue
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            facts.append(f"- {key.replace('_', ' ')}: {value}")
    if facts:
        prompt += (
            "\n\nKnown facts about the user (from prior sessions). Use these "
            "to answer personal questions directly without calling tools, but "
            "still call set_preference to record any new preferences they "
            "state:\n" + "\n".join(facts)
        )
    return prompt


def _wire_tool_call_forwarding(
    session: AgentSession[None],
    ctx: JobContext,
    log: Any,
    *,
    conv_id: UUID | None = None,
    deps: _SessionDeps | None = None,
) -> None:
    """Subscribe to ``function_tools_executed`` and forward to the room.

    Each completed tool call is emitted as a structured log line and
    sent on the ``lk.tool-calls`` text-stream topic. The frontend
    listens on that topic and renders the calls inline with the
    transcript.

    When ``conv_id`` is provided and ``deps.supabase_access_token`` is
    populated, each call also produces a ``tool`` message on the
    persisted transcript (see issue 09). The token is read from
    ``deps`` at event time rather than captured at wire time so a
    mid-session token refresh (frontend pushes a new JWT via
    participant attributes when Supabase auto-refreshes) is picked up
    by every subsequent persist call.
    """

    async def _forward(event: FunctionToolsExecutedEvent) -> None:
        for call, output in event.zipped():
            try:
                args = json.loads(call.arguments) if call.arguments else {}
            except json.JSONDecodeError:
                args = {"_raw": call.arguments}
            payload = {
                "id": call.call_id,
                "name": call.name,
                "args": args,
                "result": output.output if output is not None else None,
                "error": bool(output.is_error) if output is not None else False,
            }
            log.info(
                "agent.tool_call",
                tool=call.name,
                call_id=call.call_id,
                error=payload["error"],
            )
            if conv_id is not None and deps is not None:
                _persist_tool_message(
                    conv_id=conv_id,
                    supabase_token=deps.supabase_access_token,
                    log=log,
                    tool_name=call.name,
                    tool_args=args if isinstance(args, dict) else {"_raw": args},
                    tool_result=payload["result"],
                )
            try:
                await ctx.room.local_participant.send_text(
                    json.dumps(payload),
                    topic=TOOL_CALLS_TOPIC,
                )
            except Exception as exc:  # noqa: BLE001 — best-effort forward
                log.warning("agent.tool_call.forward_failed", error=str(exc))

    def _on_executed(event: FunctionToolsExecutedEvent) -> None:
        # The session emits sync; schedule the async forwarder on the
        # running loop so we don't block event dispatch.
        import asyncio

        asyncio.create_task(_forward(event))

    session.on("function_tools_executed", _on_executed)


# ---------------------------------------------------------------------------
# Issue 09 — conversation persistence hooks.
# ---------------------------------------------------------------------------
# Subscribes the agent session to the LiveKit transcript events so that
# every voice conversation produces:
#
#   * one `conversations` row at session start (`core.conversations.start`),
#   * one `messages` row per user/assistant utterance (committed transcript
#     items via the `conversation_item_added` event),
#   * one `messages` row per tool call (via `function_tools_executed`),
#   * an `ended_at` + auto-generated summary at session end.
#
# The session-bootstrap path that supplies the user's Supabase access
# token is wired up incrementally — see `_resolve_supabase_token` for
# the current source. When it is missing, the hooks degrade gracefully:
# they log a warning and skip the persistence call rather than tearing
# down a live conversation.


SUPABASE_TOKEN_ATTRIBUTE = "supabase_access_token"
"""Participant attribute key the frontend writes the live Supabase JWT to.

Attributes are mutable (LiveKit Cloud relays attribute changes to other
participants in real time), so the frontend pushes a refreshed token
here on Supabase's ``TOKEN_REFRESHED`` event and the agent picks it up
without having to reissue the LiveKit token. This is what keeps RLS
writes working across the Supabase access-token TTL (1h by default).
"""


def _resolve_supabase_token(participant: Any) -> str | None:
    """Recover the user's Supabase JWT for token-scoped persistence.

    Two sources are checked, in order:

    1. The participant attribute ``supabase_access_token`` — the live,
       mutable channel the frontend writes both at connect time and on
       every Supabase ``TOKEN_REFRESHED`` event. This is the path that
       survives the Supabase JWT's 1h TTL across long sessions.
    2. The participant's join-token metadata blob (the legacy path —
       see :func:`core.livekit.issue_token`). Wire shape:
       ``{"supabase_access_token": "<jwt>"}`` JSON-encoded. Retained as
       a fallback for older clients that do not yet push attributes.

    Reads from the remote participant — the agent's own
    ``ctx.token_claims()`` carries the agent's empty metadata, not the
    user's.

    The graceful-degrade fallback (return ``None``) is kept as defence
    in depth — older clients, manual ``livekit dispatch`` invocations,
    and tests that mint tokens without metadata or attributes still
    produce a workable session, just one where the persistence hooks
    log a warning and skip the write rather than tearing down the call.
    """
    attributes = getattr(participant, "attributes", None)
    if isinstance(attributes, dict):
        attr_token = attributes.get(SUPABASE_TOKEN_ATTRIBUTE)
        if isinstance(attr_token, str) and attr_token:
            return attr_token

    metadata = getattr(participant, "metadata", None)
    if not metadata:
        return None
    try:
        decoded = json.loads(metadata)
    except (TypeError, json.JSONDecodeError):
        return None
    token = decoded.get("supabase_access_token") if isinstance(decoded, dict) else None
    return str(token) if isinstance(token, str) and token else None


def _wire_supabase_token_refresh(
    room: Any,
    deps: _SessionDeps,
    log: Any,
) -> None:
    """Mutate ``deps.supabase_access_token`` whenever the frontend pushes a fresh JWT.

    livekit-rtc dispatches participant attribute updates as a Room
    event (``participant_attributes_changed``), not on the participant
    object itself. The handler signature is
    ``(changed_attrs: dict[str, str], participant: RemoteParticipant)``.

    When the frontend's Supabase client refreshes its access token it
    re-pushes ``setAttributes({supabase_access_token: <new>})``; we
    pick that up here and write it into the session deps so persistence
    and tool dispatch see the new value on the very next call.

    Defensive: failure to subscribe is logged-only — the session keeps
    running on the original (possibly soon-to-expire) token, which is
    the same posture we had before this fix.
    """

    def _on_changed(changed_attrs: Any, _participant: Any = None) -> None:
        if not isinstance(changed_attrs, dict):
            return
        new_token = changed_attrs.get(SUPABASE_TOKEN_ATTRIBUTE)
        if not isinstance(new_token, str) or not new_token:
            return
        if new_token == deps.supabase_access_token:
            return
        deps.supabase_access_token = new_token
        log.info("agent.supabase_token.refreshed")

    try:
        room.on("participant_attributes_changed", _on_changed)
    except Exception as exc:  # noqa: BLE001 — best-effort subscription
        log.warning("agent.supabase_token.refresh_wire_failed", error=str(exc))


def _wire_conversation_persistence(
    session: AgentSession[None],
    *,
    conv_id: UUID,
    deps: _SessionDeps,
    log: Any,
) -> None:
    """Subscribe to transcript events and append `messages` rows.

    Every user or assistant utterance that the realtime model commits
    to its transcript (the ``conversation_item_added`` event) becomes a
    persisted row. Tool calls are persisted from
    :func:`_wire_tool_call_forwarding` instead so we do not duplicate
    them — that handler already has the args/result in hand.

    The Supabase access token is read from ``deps`` at event time, not
    captured here at wire time. The Supabase JWT has a 1h TTL; the
    frontend pushes a refreshed token via the participant attribute
    ``supabase_access_token`` on Supabase's ``TOKEN_REFRESHED`` event,
    and the entrypoint mutates ``deps.supabase_access_token`` when the
    attribute changes. Reading-per-call is what makes that refresh
    visible to long-running sessions.

    When the token is None the hook noops with a warning. We do not
    crash the session: a logging-only degradation is preferable to
    losing a real-time conversation over a missing piece of plumbing.
    """

    def _on_item(event: ConversationItemAddedEvent) -> None:
        token = deps.supabase_access_token
        if token is None:
            log.warning("agent.conversation.append_skipped_no_token")
            return
        item = event.item
        role = getattr(item, "role", None)
        text_content_attr = getattr(item, "text_content", None)
        if callable(text_content_attr):
            content = text_content_attr() or ""
        else:
            content = str(text_content_attr or "")
        if role not in {"user", "assistant"} or not content.strip():
            # Skip system messages and empty/streaming partials —
            # `conversation_item_added` fires once per finalised item.
            return
        try:
            core_conversations.append_message(
                conv_id,
                role=role,
                content=content,
                supabase_token=token,
            )
        except Exception as exc:  # noqa: BLE001 — persistence is best-effort
            log.warning(
                "agent.conversation.append_failed",
                role=role,
                error=str(exc),
            )

    session.on("conversation_item_added", _on_item)


def _persist_tool_message(
    *,
    conv_id: UUID,
    supabase_token: str | None,
    log: Any,
    tool_name: str,
    tool_args: dict[str, Any],
    tool_result: Any,
) -> None:
    """Append a tool-call as a `tool` message on the conversation."""
    if supabase_token is None:
        return
    try:
        core_conversations.append_message(
            conv_id,
            role="tool",
            content="",
            tool_name=tool_name,
            tool_args=tool_args,
            tool_result=tool_result,
            supabase_token=supabase_token,
        )
    except Exception as exc:  # noqa: BLE001 — persistence is best-effort
        log.warning(
            "agent.conversation.tool_append_failed",
            tool=tool_name,
            error=str(exc),
        )


# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Issue 11 — TTFA metrics hook
# ---------------------------------------------------------------------------
# Subscribes the agent session to LiveKit's `metrics_collected` event
# and forwards each event to `core.observability.handle_metrics_event`,
# which emits one structured `turn_metrics` JSON log line per metric
# the framework reports (LLM TTFT, TTS TTFB, EOU delay, etc).
#
# Kept in its own helper + delimiter block so the parallel issue 07
# agent (which adds tool wiring above) and any future additions stay
# additive and do not need to interleave with this seam.


def _wire_metrics_logging(session: AgentSession[None]) -> None:
    """Forward LiveKit metrics events to the structured logger."""

    def _on_metrics(event: Any) -> None:
        handle_metrics_event(event)

    session.on("metrics_collected", _on_metrics)


# ---------------------------------------------------------------------------


async def entrypoint(ctx: JobContext) -> None:
    """LiveKit Agents entrypoint: join the room and run the voice loop.

    The function is registered with `WorkerOptions(entrypoint_fnc=...)`
    in :mod:`agent.__main__`. LiveKit invokes it once per dispatched
    job; SIGTERM and graceful shutdown are handled by the worker
    runtime.
    """
    settings = get_settings()
    setup_logging(settings)
    log = structlog.get_logger("agent.session")

    log.info(
        "agent.session.starting",
        worker_id=ctx.worker_id,
        room=ctx.room.name,
        model="openai-realtime",
    )

    await ctx.connect()

    # Wait for the user to join. The agent's own ctx claims carry an
    # auto-generated identity ("agent-AJ_…"), so we resolve the user
    # from the remote participant the dispatch was triggered for.
    participant = await ctx.wait_for_participant()

    user = _resolve_user_from_participant(participant)
    # Resolve the Supabase token from participant metadata BEFORE
    # building deps — `_SessionDeps.supabase_access_token` is what the
    # tool dispatcher reads to forward the user's JWT to RLS-scoped
    # core operations (set_preference, remember, conversation
    # persistence). Without it, every tool no-ops with a "no
    # credentials" message.
    supabase_token = _resolve_supabase_token(participant)
    deps = _SessionDeps(
        user=user,
        log=log.bind(user_id=str(user.id)),
        supabase_access_token=supabase_token,
    )

    # ------------------------------------------------------------------
    # Issue 11 — bind session-scoped contextvars so every log line
    # emitted during the session (including the per-turn metrics
    # lines) carries `session_id` and `user_id`. The room name doubles
    # as the session id.
    # Issue 09 — once the conversation row is created, also bind
    # `conversation_id` so every subsequent log line correlates back
    # to the persisted transcript.
    # ------------------------------------------------------------------
    session_id = ctx.room.name
    user_id_str = str(user.id)
    bind_log_context(session_id=session_id, user_id=user_id_str)
    conv_id: UUID | None = None
    if supabase_token is not None:
        try:
            conv_id = core_conversations.start(user, supabase_token=supabase_token)
            bind_log_context(conversation_id=str(conv_id))
            log.info("agent.conversation.started", conversation_id=str(conv_id))
        except Exception as exc:  # noqa: BLE001 — degrade rather than crash
            log.warning("agent.conversation.start_failed", error=str(exc))
            conv_id = None
    else:
        log.info("agent.conversation.skipped_no_token")

    # Issue 10 — read settings-page preferences (preferred_name, voice)
    # and thread them into the realtime model + system prompt. Both
    # degrade to None silently when the token is missing or the read
    # fails; the voice loop must keep working before persistence is
    # wired end-to-end.
    preferred_name, voice, all_prefs = _load_user_preferences(user, supabase_token, log)
    session = build_session(settings, voice=voice)
    agent = build_agent(deps, instructions=build_system_prompt(preferred_name, all_prefs))

    _wire_tool_call_forwarding(
        session,
        ctx,
        log,
        conv_id=conv_id,
        deps=deps,
    )
    _wire_metrics_logging(session)
    if conv_id is not None:
        _wire_conversation_persistence(
            session,
            conv_id=conv_id,
            deps=deps,
            log=log,
        )

    # Issue 14 — keep the Supabase token fresh. The frontend pushes a
    # new JWT to the `supabase_access_token` participant attribute on
    # Supabase's `TOKEN_REFRESHED` event; we mutate `deps` in-place so
    # every persistence and tool-dispatch path sees the new value on
    # its next call. Without this, sessions over the Supabase JWT TTL
    # (1h by default) start emitting PGRST303 "JWT expired".
    _wire_supabase_token_refresh(ctx.room, deps, log)

    log.info(
        "agent.session.ready",
        worker_id=ctx.worker_id,
        room=ctx.room.name,
        user_id=user_id_str,
        tools=[t.name for t in all_tools()],
    )

    try:
        await session.start(agent, room=ctx.room)
    finally:
        # Issue 09 — close out the conversation row and let the
        # summariser run (when the threshold is met). The end call is
        # best-effort: we still tear down the structlog context even
        # if the database round-trip fails.
        if conv_id is not None and supabase_token is not None:
            try:
                core_conversations.end(conv_id, supabase_token=supabase_token)
                log.info("agent.conversation.ended", conversation_id=str(conv_id))
            except Exception as exc:  # noqa: BLE001 — best-effort summary
                log.warning("agent.conversation.end_failed", error=str(exc))
        unbind_log_context("session_id", "user_id", "conversation_id")


AGENT_NAME = "voice-ai-assistant"
"""The name LiveKit dispatch uses to route rooms to this worker.

livekit-agents 1.x deprecated implicit/automatic dispatch — workers
that register without an ``agent_name`` no longer pick up rooms by
default. Tokens minted by ``core.livekit.issue_token`` request this
name via a ``RoomAgentDispatch`` entry so a connecting browser
triggers a dispatch immediately.
"""


def worker_options() -> WorkerOptions:
    """Build the :class:`WorkerOptions` the CLI uses to register the worker.

    Pulls LiveKit credentials from the typed settings rather than
    relying on the implicit ``LIVEKIT_*`` environment lookup the
    livekit-agents CLI does — this keeps the configuration seam
    consistent with the rest of the codebase.
    """
    settings = get_settings()
    return WorkerOptions(
        entrypoint_fnc=entrypoint,
        agent_name=AGENT_NAME,
        ws_url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )


__all__ = [
    "SYSTEM_PROMPT",
    "TOOL_CALLS_TOPIC",
    "build_agent",
    "build_session",
    "build_system_prompt",
    "entrypoint",
    "worker_options",
]
