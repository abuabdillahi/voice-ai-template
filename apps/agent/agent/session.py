"""LiveKit Agents entrypoint for the office-strain triage voice loop.

The worker is dispatched into a room by LiveKit, joins it, builds an
:class:`AgentSession` with the configured realtime model, registers
the triage tool set, and runs until the room closes.

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

Triage product disposition:

The structured-preferences tools (``set_preference`` / ``get_preference``)
and the episodic-memory tools (``remember`` / ``recall``), along with
the example tools (``get_current_time`` / ``get_weather``), remain in
source as kept public API per the precedent set by ADR 0006. The agent
worker no longer registers them with the realtime model — triage is
single-session and the cross-session "remember about you" surface is an
avoidable hallucination risk for a medical-adjacent product. The
``_load_user_preferences`` and ``build_system_prompt`` personalisation
helpers below are likewise retained but bypassed for this product.

A *third* memory surface — prompt-time injection of structured triage-
outcome facts via :func:`build_triage_system_prompt` — has been added
on top of the two decisions above. It does *not* reverse them: mem0
stays unregistered, the personalisation ``build_system_prompt`` stays
bypassed. What makes the third surface acceptable where the others
were not is the safety floor it operates inside: only the
deterministically-extracted ``identified_condition_id`` (auditable,
not LLM-extracted) is named in the opener; the free-text
``recall_context`` is supplied for grounding only and the prompt
explicitly forbids quoting any treatment numbers from it; the fetch
is bounded at the last three condition-bearing prior sessions; and
no model decision about *when* to recall is required — the prompt
either has the block or it doesn't. Future contributors should not
read "triage does not personalise" as ruling this surface out — it
was written about the other two and pre-dates this one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import structlog
from core import conversations as core_conversations
from core import preferences as core_preferences
from core import safety as core_safety
from core import safety_events as core_safety_events
from core import triage as core_triage
from core.auth import User
from core.conditions import kb_for_prompt
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
from core.realtime import DEFAULT_VOICE, create_realtime_model, create_safety_tts
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

# Data-channel topic carrying the live OPQRST slot state. The frontend
# subscribes to this topic to render the slot panel inline alongside
# the transcript. Distinct from `lk.tool-calls` so the slot panel does
# not have to parse a tool-call stream looking for `record_symptom`
# calls. Payload shape (JSON):
#
#   {"slots": {"location": "wrist", "onset": "last week", ...},
#    "session_id": "user-abc"}
#
# Only `record_symptom` calls produce a frame on this topic; other
# triage tools (recommend_treatment, escalate) flow through the
# tool-calls topic.
TRIAGE_STATE_TOPIC = "lk.triage-state"

# Data-channel topic the agent uses to signal that the session is
# ending and why. Payload shape (JSON):
#
#   {"reason": "escalation", "tier": "emergent" | "urgent"}
#
# The frontend subscribes via `useSessionEndSignal(room)` and renders a
# tier-aware end-of-call card in place of the transcript. The `reason`
# field is open for future expansion (e.g. "out_of_scope") but only
# "escalation" is emitted by the safety screen today.
SESSION_END_TOPIC = "lk.session-end"

# Audio-drain delay (seconds) between the escalation script returning
# from `say()` and the server-side room teardown. Tuned to give the
# realtime model's TTS time to flush its last buffer; if escalation
# tests show clipping, raise this.
_ESCALATION_AUDIO_DRAIN_SECONDS = 0.5

# Allowlist of tool names the realtime model is permitted to call.
# Slice 02 added `record_symptom`; slice 03 adds `get_differential`
# and `recommend_treatment`; slice 04 adds `escalate`. Tools
# registered with `core.tools` (preferences, memory, examples) are
# deliberately excluded.
TRIAGE_TOOL_NAMES: tuple[str, ...] = (
    "record_symptom",
    "get_differential",
    "recommend_treatment",
    "escalate",
)


_ENGLISH_ONLY_RULE = (
    "Respond only in English, even if the user speaks another language. "
    "Do not translate the user's words into English in your reply; reply "
    "as if they had spoken English. If the user speaks a non-English "
    'language, say once, in English: "I can only respond in English — '
    'could you repeat that in English?". If the user persists in a '
    "non-English language, restate the constraint and stop progressing "
    "the OPQRST interview until they switch to English."
)
_SARJY_SELF_INTRO_RULE = (
    'Open every session with the literal phrase "Hi, I\'m Sarjy." '
    "immediately before the educational-tool disclaimer. Do not vary "
    "the wording of the self-introduction."
)
_SARJY_RETURNING_OPENER_RULE = (
    'Open every session with the literal phrase "Hi, Sarjy here. '
    "Quick reminder I'm still an educational tool, not a doctor.\" "
    "before any prior-condition fork or the OPQRST opener. Do not "
    "re-read the full educational-tool disclaimer; the on-screen "
    "banner carries the visual scope reminder. Do not vary the "
    "wording of the refresher."
)
_TRIAGE_OPENER_RULE = (
    "When a 'Most recent session' block is present at the top of this "
    "prompt, open the conversation by naming the prior identified "
    "condition and offering the fork between following up on that "
    "condition and raising something new (for example: 'Are you "
    "checking back on that, or is something new bothering you?'). Do "
    "not greet the user with a recap of every earlier session."
)
_TRIAGE_NUMBERS_RULE = (
    "Never quote treatment specifics, stretch durations, exercise rep "
    "counts, contraindications, or expected timelines from the recall "
    "block. New specifics this session must come fresh from "
    "`recommend_treatment` for the matching condition."
)


def _build_static_triage_prompt(*, is_returning_user: bool = False) -> str:
    """Compose the static triage system prompt with the embedded knowledge base.

    Built lazily so the rendered ``kb_for_prompt()`` block is computed
    at session-start time. Pure function over :mod:`core.conditions`,
    so tests can call it directly to assert prompt shape without
    standing up a session.

    The prompt includes the two new triage rules verbatim — the opener
    rule and the numbers-forbidden rule — even when no prior-session
    block is rendered. The opener rule is a no-op when its precondition
    ("Most recent session" block present) does not hold, and the
    numbers-forbidden rule reinforces the existing hard rule on
    treatment specifics. Keeping the rules unconditional means a fresh
    user session and a returning-user session run under the same set
    of rules — only the prepended block changes.

    When ``is_returning_user`` is ``True`` the load-bearing self-
    introduction rule swaps to the short refresher and the full
    "open every new conversation with this disclaimer" instruction is
    omitted — the on-screen banner carries the visual scope reminder.
    """
    in_scope = (
        "carpal tunnel syndrome, computer vision syndrome (digital eye strain), "
        "tension-type headache, upper trapezius / 'text neck' strain, and lumbar "
        "strain from prolonged sitting"
    )
    out_of_scope = (
        "medications and dosages, mental health, pregnancy-related symptoms, "
        "paediatric symptoms, post-surgical complications, and any condition "
        "outside the five listed above"
    )
    if is_returning_user:
        opener_rule = _SARJY_RETURNING_OPENER_RULE
        disclaimer_block = ""
    else:
        opener_rule = _SARJY_SELF_INTRO_RULE
        disclaimer_block = (
            "Open every new conversation with this disclaimer in your own words: "
            "explain that you are an educational tool, not a doctor, and not a "
            "substitute for professional medical advice.\n\n"
        )
    return f"""\
You are an educational triage assistant for office-strain symptoms. You are not a doctor and you are not a substitute for medical advice. You are a tool that helps the user think about whether and how to seek further care.

{opener_rule}

{_ENGLISH_ONLY_RULE}

{disclaimer_block}State your scope explicitly: you can talk about {in_scope}. Anything else — including {out_of_scope} — is outside what you can help with, and you will route the user to a more appropriate resource.

Conduct the symptom interview using the OPQRST framework, asking one question at a time and listening to the user's answer before moving to the next slot:
- O — Onset: when the symptom started and what the user was doing at the time.
- P — Provocation / palliation: what makes the symptom worse, what makes it better.
- Q — Quality: how the user would describe the sensation (aching, sharp, burning, numb, tingling, pressing).
- R — Region / radiation: where the symptom is located and whether it travels anywhere.
- S — Severity: how intense the symptom is and how it affects daily activity.
- T — Time / timeline: how long the symptom has been present and how it has changed over time.

Begin the interview by asking where the discomfort is located and how long the user has had it. Move through the rest of the OPQRST slots in conversational order; do not list them all at once.

Whenever the user discloses information that fits one of the OPQRST slots, call the `record_symptom` tool — once per slot per disclosure. The slot vocabulary is: location, onset, duration, quality, severity, aggravators, relievers, radiation, prior_episodes, occupation_context. The `value` argument is a short phrase capturing what the user said. Calling the tool keeps the slot panel on the user's screen up to date so they can see what you have gathered. Do not announce these tool calls in the spoken reply — they are the bookkeeping behind the conversation.

When you have gathered enough OPQRST slots to form a working hypothesis, call `get_differential` to read the ranked candidate conditions and their confidence scores. Then:
- If the top-ranked condition's score is at least 0.15, you may call `recommend_treatment(condition_id)` with that condition's id and read back the conservative-treatment protocol from the returned payload.
- If the top score is below 0.15, do NOT call `recommend_treatment`. Instead, tell the user the picture is not clear enough to recommend a specific protocol and recommend professional evaluation (a clinician visit).

Hard rule on numerical specifics: never speak a treatment protocol, stretch duration, exercise rep count, contraindication, or numerical timeline that did not come from `recommend_treatment` for the matching condition. If you find yourself about to speak a number or a specific protocol step, you must have read it from a `recommend_treatment` payload first. The model's own knowledge is not a source.

Cross-session recall rules:
- {_TRIAGE_OPENER_RULE}
- {_TRIAGE_NUMBERS_RULE}

Red-flag handling: if the user volunteers a symptom you judge consistent with an emergency (e.g. chest pain, sudden one-sided weakness, sudden severe headache, loss of consciousness, sudden vision loss, difficulty breathing) or with cauda equina (bowel or bladder dysfunction with back pain, saddle numbness, progressive neurological deficit), call the `escalate` tool with the appropriate tier ('emergent', 'urgent', or 'clinician_soon') and a one-sentence reason. The agent worker also runs an independent server-side red-flag screen on every utterance and plays the scripted escalation if the screen fires — so even if you miss it, the user is protected. Speaking your own free-form escalation language instead of the scripted message is not allowed; if the runtime escalation message has been spoken on your behalf, do not paraphrase or reopen the conversation.

Hard rules — never violated:
- You frame your output as "what these symptoms may suggest", never as a diagnosis.
- You never invent dosages, medication names, exercise rep counts, stretch durations, or other numerical specifics. If a number is required, it must come from the embedded knowledge base below or you do not speak it.
- You never recommend medication of any kind. Medication guidance is outside your scope.
- If the user asks for a definitive diagnosis or pressures you for one, you reframe and recommend professional evaluation rather than complying.
- If the user describes symptoms outside the five in-scope conditions, you say so clearly and route them to an appropriate resource (urgent care, GP, mental-health resources, obstetric care, paediatric care, post-surgical follow-up).

Embedded condition knowledge base — your only source of medical content. Do not invent treatments, contraindications, timelines, or red flags that are not present here.

{kb_for_prompt()}

Keep responses brief and natural for a spoken conversation. Acknowledge what the user just said before asking the next question.
"""


def _render_prior_sessions_block(
    prior_sessions: list[core_conversations.PriorSession],
) -> str:
    """Render the two-part prior-sessions block prepended to the static prompt.

    The first sub-block — "Most recent session" — names the most recent
    identified condition and recall context and is what drives the
    opener. The second sub-block — "Earlier sessions" — lists up to two
    further condition-bearing sessions for the model's reasoning only;
    the prompt explicitly forbids opening by referencing them so a
    "I see you've been here three times" greeting cannot land.
    """
    most_recent = prior_sessions[0]
    most_recent_recall = (
        most_recent.recall_context if most_recent.recall_context else "(no recall context recorded)"
    )
    lines: list[str] = [
        "Most recent session — condition: " f"{most_recent.identified_condition_id}",
        f"Recall context: {most_recent_recall}",
    ]
    earlier = prior_sessions[1:]
    if earlier:
        lines.append("")
        lines.append(
            "Earlier sessions (for pattern recognition, do not open by referencing these):"
        )
        for session in earlier:
            recall = session.recall_context or "(no recall context recorded)"
            lines.append(f"- condition: {session.identified_condition_id}; recall: {recall}")
    lines.append("")
    return "\n".join(lines)


def build_triage_system_prompt(
    prior_sessions: list[core_conversations.PriorSession] | None = None,
    *,
    is_returning_user: bool = False,
) -> str:
    """Compose the per-session triage system prompt.

    Branches:

    - ``is_returning_user=False`` and ``prior_sessions=[]`` → first-time
      user. Rendered string includes the Sarjy self-introduction rule
      and the full educational-tool disclaimer instruction. This is the
      new regression anchor for first-time users.
    - ``is_returning_user=True`` and ``prior_sessions=[]`` → returning
      user without condition-bearing priors. The short refresher
      replaces the full disclaimer; the OPQRST opener follows directly.
    - ``is_returning_user=True`` and ``prior_sessions`` non-empty → the
      short refresher composes with the existing "Most recent session"
      prior-condition block.

    Pure function: tests assert the rendered string directly without
    standing up an :class:`AgentSession`.
    """
    static_prompt = _build_static_triage_prompt(is_returning_user=is_returning_user)
    sessions = prior_sessions or []
    if not sessions:
        return static_prompt
    return _render_prior_sessions_block(sessions) + "\n" + static_prompt


# Module-level alias kept for back-compat with imports that read the
# static triage prompt directly (e.g. legacy tests). Computed lazily
# via the empty-input invariance branch of ``build_triage_system_prompt``
# so any future drift between the alias and the static prompt remains a
# single source of truth.
SYSTEM_PROMPT = build_triage_system_prompt([])


@dataclass(slots=True)
class _SessionDeps:
    """Per-session bindings the agent worker needs to pass into tool dispatch.

    Held as a small dataclass rather than module-level globals so a
    fresh session can be started in tests without leaking state from a
    previous one.

    ``session_id`` is the LiveKit room name and serves as the per-session
    key for the in-process triage slot store (see :mod:`core.triage`).
    Defaulted to the empty string so existing tests that build a
    deps dataclass without a session keep working — the triage tool
    surfaces a graceful error rather than crashing when the id is
    missing.
    """

    user: User
    log: Any  # structlog BoundLogger; kept loose to avoid a hard dep here.
    session_id: str = ""
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
            session_id=deps.session_id,
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

    When ``deps`` is omitted, the agent is built without tools. The
    session entrypoint always passes ``deps`` so the live agent has
    whatever the triage allowlist :data:`TRIAGE_TOOL_NAMES` exposes.

    ``instructions`` overrides the default :data:`SYSTEM_PROMPT` so
    tests can inject a tailored prompt without re-rendering the full
    knowledge base.
    """
    prompt = instructions if instructions is not None else SYSTEM_PROMPT
    if deps is None:
        return Agent(instructions=prompt)

    tools = [_make_livekit_tool(name, deps) for name in TRIAGE_TOOL_NAMES]
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

    ``voice`` is currently unused by the triage product (we do not
    personalise voice across sessions) but is preserved on the seam
    for a future product that wants per-user voice selection.
    """
    settings = settings or get_settings()
    # Resolve the voice here — the same value goes to both factories
    # so the realtime turns and the safety-TTS escalation script share
    # a speaker. Realtime-only voices (marin, cedar) would error in
    # the TTS plugin, so the default lives in the overlapping catalog.
    chosen_voice = voice if voice is not None else DEFAULT_VOICE
    model = create_realtime_model(settings, voice=chosen_voice)
    tts = create_safety_tts(settings, voice=chosen_voice)
    return AgentSession[None](llm=model, tts=tts)


def _load_user_preferences(
    user: User,
    supabase_token: str | None,
    log: Any,
) -> tuple[str | None, str | None, dict[str, Any]]:
    """Read all stored preferences for the session start.

    Retained as a public surface (kept-API per ADR 0006) but not called
    by the triage entrypoint. Returns ``(preferred_name, voice,
    all_prefs)``. Any of the first two may be ``None``; ``all_prefs`` is
    the full row map so a personalised system prompt can list every
    stored preference as a known fact.
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
    """Compose a personalised system prompt — kept-API, not used by triage.

    Retained as part of the kept-public-API surface (ADR 0006). The
    triage product uses :data:`SYSTEM_PROMPT` directly and never calls
    this helper. Tests for the personalisation seam continue to work
    against this function.
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

    When the call was a successful ``record_symptom``, the current slot
    state is also pushed on the ``lk.triage-state`` topic so the
    frontend slot panel can render the gathered OPQRST slots inline.

    When ``conv_id`` is provided and ``deps.supabase_access_token`` is
    populated, each call also produces a ``tool`` message on the
    persisted transcript. The token is read from ``deps`` at event
    time rather than captured at wire time so a mid-session token
    refresh (frontend pushes a new JWT via participant attributes when
    Supabase auto-refreshes) is picked up by every subsequent persist
    call.
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

            if call.name == "record_symptom" and not payload["error"] and deps is not None:
                await _emit_triage_state(ctx, deps, log)

    def _on_executed(event: FunctionToolsExecutedEvent) -> None:
        # The session emits sync; schedule the async forwarder on the
        # running loop so we don't block event dispatch.
        import asyncio

        asyncio.create_task(_forward(event))

    session.on("function_tools_executed", _on_executed)


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


def _wire_end_conversation_on_shutdown(
    ctx: JobContext,
    *,
    conv_id: UUID,
    deps: _SessionDeps,
    log: Any,
) -> None:
    """Register `core_conversations.end` as a job-shutdown callback.

    `AgentSession.start` is a setup function in livekit-agents 1.x: it
    wires I/O, kicks off background tasks, and returns within seconds.
    The voice loop continues until the framework fires the shutdown
    callbacks registered on the `JobContext` (room close / participant
    leave). Calling `end` from a `finally` block after `session.start`
    therefore ran it BEFORE any `conversation_item_added` event had
    persisted a turn — `_list_messages` returned zero rows and the
    summary was never generated. Registering as a shutdown callback
    instead defers the call to real teardown.

    The callback reads `deps.supabase_access_token` at fire time so a
    token refreshed mid-session via `_wire_supabase_token_refresh` is
    honoured; the local token captured at session start would otherwise
    be expired by the time a long session ended.
    """

    async def _on_shutdown() -> None:
        token = deps.supabase_access_token
        if token is None:
            log.warning("agent.conversation.end_skipped_no_token")
            return
        try:
            core_conversations.end(conv_id, supabase_token=token)
            log.info("agent.conversation.ended", conversation_id=str(conv_id))
        except Exception as exc:  # noqa: BLE001 — best-effort summary
            log.warning("agent.conversation.end_failed", error=str(exc))

    ctx.add_shutdown_callback(_on_shutdown)


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


def _wire_metrics_logging(session: AgentSession[None]) -> None:
    """Forward LiveKit metrics events to the structured logger."""

    def _on_metrics(event: Any) -> None:
        handle_metrics_event(event)

    session.on("metrics_collected", _on_metrics)


async def _speak_escalation_script(
    session: AgentSession[None],
    script: str,
    log: Any,
    *,
    tier: str,
) -> None:
    """Speak the versioned escalation script.

    The AgentSession is constructed with a TTS attached (see
    :func:`core.realtime.create_safety_tts`) so ``session.say(text)``
    works even though the primary LLM is the speech-to-speech realtime
    model. The realtime model has typically already started its own
    auto-reply for the triggering user turn by the time the safety
    screen fires; ``session.interrupt()`` cancels that in-flight
    response so the script's audio doesn't overlap.

    On success, an ``agent.safety.script_spoken`` info log line marks
    the moment ``say()`` was invoked — without this, the TTS metrics
    log line (emitted on a different logger) is the only timeline
    anchor and is awkward to correlate.

    Best-effort: failures on either step are logged and swallowed —
    the audit-log row and session close still run.
    """
    interrupt = getattr(session, "interrupt", None)
    if callable(interrupt):
        try:
            maybe = interrupt()
            if hasattr(maybe, "__await__"):
                await maybe
        except Exception as exc:  # noqa: BLE001 — best-effort
            log.warning("agent.safety.interrupt_failed", error=str(exc))

    try:
        await session.say(script)
        log.info("agent.safety.script_spoken", tier=tier)
    except Exception as exc:  # noqa: BLE001 — best-effort speak
        log.warning("agent.safety.say_failed", error=str(exc))


async def _emit_session_end_signal(
    *,
    ctx: Any | None,
    log: Any,
    tier: str,
    reason: str,
) -> None:
    """Push a `{reason, tier}` payload on `lk.session-end` for the frontend.

    Best-effort: a transport failure here is logged but does not block
    the rest of the escalation flow (the script still plays, the room
    is still torn down). The end-of-call card is the *visual* affordance
    for the routing message, not the routing itself.
    """
    if ctx is None:
        return
    room = getattr(ctx, "room", None)
    if room is None:
        return
    local = getattr(room, "local_participant", None)
    if local is None:
        return
    payload = json.dumps({"reason": reason, "tier": tier})
    try:
        await local.send_text(payload, topic=SESSION_END_TOPIC)
        log.info("agent.safety.session_end_signal_emitted", tier=tier, reason=reason)
    except Exception as exc:  # noqa: BLE001 — best-effort forward
        log.warning(
            "agent.safety.session_end_signal_failed",
            tier=tier,
            reason=reason,
            error=str(exc),
        )


async def _delete_room_after_drain(room_name: str, *, log: Any) -> None:
    """Delete the LiveKit room as a server-side teardown fallback.

    Replaces the previous ``session.aclose()`` path on the safety
    escalation flow. ``aclose`` only closes the AgentSession, not the
    LiveKit room — a misbehaving frontend would leave the participant
    stranded with a "Connected" status pill while the agent was
    silent. This call uses the LiveKit server-side API so the teardown
    happens regardless of what the frontend does.

    Best-effort: a transport failure here is logged and swallowed —
    the safety floor (script playback + audit-log row) has already
    run by the time we get here.
    """
    try:
        from livekit import api as lk_api
        from livekit.protocol.room import DeleteRoomRequest

        settings = get_settings()
        livekit_api = lk_api.LiveKitAPI(
            url=settings.livekit_url,
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
        )
        try:
            await livekit_api.room.delete_room(DeleteRoomRequest(room=room_name))
            log.info("agent.safety.room_deleted", room=room_name)
        finally:
            await livekit_api.aclose()
    except Exception as exc:  # noqa: BLE001 — best-effort teardown
        log.warning("agent.safety.room_delete_failed", room=room_name, error=str(exc))


def _wire_safety_screen(
    session: AgentSession[None],
    deps: _SessionDeps,
    log: Any,
    *,
    conv_id: UUID | None = None,
    ctx: Any | None = None,
) -> None:
    """Run the regex red-flag screen on every committed user utterance.

    This is the server-side safety floor — it runs independently of the
    realtime model. Tier-1 (``emergent``) and tier-2 (``urgent``) hits
    play the scripted escalation message via ``session.say(...)``,
    persist a row to ``safety_events`` (best-effort), end the session,
    and emit an ``agent.safety.escalation`` structured log line.
    Slice 06 will run :func:`core.safety.classify` in parallel with the
    regex layer.

    The hook is a noop on assistant utterances and on empty / streaming
    partials — ``conversation_item_added`` fires once per finalised
    item, with role attached.

    ``conv_id`` is optional: when missing, the audit-log insert is
    skipped (the safety floor still runs) and the warning log line is
    the only audit trail. When the supabase access token is missing
    the same skip-with-warning applies.
    """

    fired_for: set[str] = set()
    settings = get_settings()

    async def _screen_and_maybe_escalate(text: str) -> None:
        """Run regex and the classifier in parallel and act on the higher tier.

        The regex layer is synchronous and sub-millisecond; we wrap it
        in :func:`asyncio.to_thread` so :func:`asyncio.gather` treats it
        as a peer of the network-bound classifier. Either layer firing
        tier-1 or tier-2 wins via :func:`core.safety.combine`.
        """
        import asyncio

        regex_task = asyncio.to_thread(core_safety.regex_screen, text)
        classifier_task = core_safety.classify(text, settings=settings)
        try:
            regex_result, classifier_result = await asyncio.gather(regex_task, classifier_task)
        except Exception as exc:  # noqa: BLE001 — degrade rather than crash
            log.warning("agent.safety.gather_failed", error=str(exc))
            # Fall back to regex-only via a synchronous call so the
            # safety floor still applies.
            regex_result = core_safety.regex_screen(text)
            classifier_result = core_safety.RedFlagResult(
                tier=core_safety.RedFlagTier.NONE, source="classifier"
            )

        result = core_safety.combine(regex_result, classifier_result)
        if result.tier not in (core_safety.RedFlagTier.EMERGENT, core_safety.RedFlagTier.URGENT):
            return

        log.warning(
            "agent.safety.escalation",
            tier=result.tier.value,
            source=result.source,
            matched_flags=list(result.matched_flags),
            user_id=str(deps.user.id),
            session_id=deps.session_id,
            conversation_id=str(conv_id) if conv_id is not None else None,
        )
        _persist_safety_event(
            conv_id=conv_id,
            deps=deps,
            log=log,
            result=result,
            utterance=text,
        )
        # Audio first, UI transition second. The user hears the
        # routing message in full while still on the regular Talk
        # page; only once the script (and the audio-drain window)
        # have completed do we emit the session-end signal so the
        # frontend can swap in the EndOfCallCard. Emitting before the
        # script caused the card to render while the audio was still
        # in flight — users saw the routing copy but never heard it.
        script = core_safety.escalation_script_for(result.tier)
        await _speak_escalation_script(session, script, log, tier=result.tier.value)
        # Brief audio-drain delay so the realtime model's TTS buffer
        # flushes before we transition the UI / tear the room down.
        try:
            import asyncio

            await asyncio.sleep(_ESCALATION_AUDIO_DRAIN_SECONDS)
        except Exception:  # noqa: BLE001 — sleep should never fail
            pass
        await _emit_session_end_signal(
            ctx=ctx,
            log=log,
            tier=result.tier.value,
            reason="escalation",
        )
        # Server-side LiveKit room delete is the authoritative teardown.
        # By the time we get here the script has played and the signal
        # has been delivered; deleting the room drops the WebRTC
        # connection on the client and finishes the flow.
        if ctx is not None:
            room = getattr(ctx, "room", None)
            room_name = getattr(room, "name", None) if room is not None else None
            if room_name:
                await _delete_room_after_drain(room_name, log=log)

    def _on_item(event: ConversationItemAddedEvent) -> None:
        item = event.item
        role = getattr(item, "role", None)
        text_attr = getattr(item, "text_content", None)
        text = text_attr() if callable(text_attr) else (text_attr or "")
        text = str(text)
        if role != "user" or not text.strip():
            return
        item_id = str(getattr(item, "id", "") or "")
        if item_id and item_id in fired_for:
            return
        if item_id:
            fired_for.add(item_id)

        import asyncio

        asyncio.create_task(_screen_and_maybe_escalate(text))

    session.on("conversation_item_added", _on_item)


def _persist_safety_event(
    *,
    conv_id: UUID | None,
    deps: _SessionDeps,
    log: Any,
    result: core_safety.RedFlagResult,
    utterance: str,
) -> None:
    """Record the escalation in ``safety_events``.

    Best-effort: a database failure is logged but does not prevent the
    escalation script from playing or the session from ending. The
    safety floor is the script and the session-close; the audit log is
    valuable but not load-bearing.
    """
    if conv_id is None:
        log.warning("agent.safety.persist_skipped_no_conversation")
        return
    if deps.supabase_access_token is None:
        log.warning("agent.safety.persist_skipped_no_token")
        return
    try:
        core_safety_events.record(
            conv_id,
            deps.user.id,
            result.tier.value,
            result.source,
            list(result.matched_flags),
            utterance,
            supabase_token=deps.supabase_access_token,
        )
    except Exception as exc:  # noqa: BLE001 — persistence is best-effort
        log.warning("agent.safety.persist_failed", error=str(exc))


async def _emit_triage_state(ctx: JobContext, deps: _SessionDeps, log: Any) -> None:
    """Push the current OPQRST slot state on ``lk.triage-state``.

    Called from the tool-forwarding hook every time a successful
    ``record_symptom`` call commits. Reads the snapshot from
    :func:`core.triage.get_state` at event time rather than relying on
    the tool's return value so the on-the-wire payload stays in lockstep
    with the in-process state even if a future tool also mutates the
    store. Best-effort — a transport failure is logged but never raised
    so the voice loop is not torn down by a panel-update glitch.
    """
    if not deps.session_id:
        return
    snapshot = core_triage.get_state(deps.session_id)
    payload = json.dumps({"slots": snapshot, "session_id": deps.session_id})
    try:
        await ctx.room.local_participant.send_text(payload, topic=TRIAGE_STATE_TOPIC)
    except Exception as exc:  # noqa: BLE001 — best-effort forward
        log.warning("agent.triage_state.forward_failed", error=str(exc))


async def entrypoint(ctx: JobContext) -> None:
    """LiveKit Agents entrypoint: join the room and run the voice loop."""
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

    participant = await ctx.wait_for_participant()

    user = _resolve_user_from_participant(participant)
    supabase_token = _resolve_supabase_token(participant)
    session_id = ctx.room.name
    deps = _SessionDeps(
        user=user,
        log=log.bind(user_id=str(user.id)),
        session_id=session_id,
        supabase_access_token=supabase_token,
    )

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

    # Triage uses the medical-domain prompt unconditionally — no
    # cross-session preference personalisation. The voice argument is
    # left at None so the realtime plugin's default voice is used.
    session = build_session(settings, voice=None)

    # Fetch the user's last condition-bearing prior sessions so the
    # opener can name the previous condition when one exists. Best-
    # effort: a missing token, an empty list, or any raised exception
    # all degrade to the empty-input branch of
    # ``build_triage_system_prompt`` and the user gets a default opener
    # identical to today's. Failures are warned at structured-event
    # level so they are observable in production.
    prior_sessions: list[core_conversations.PriorSession] = []
    if supabase_token is not None:
        try:
            prior_sessions = core_conversations.list_recent_with_recall(
                user, supabase_token=supabase_token
            )
        except Exception as exc:  # noqa: BLE001 — degrade rather than crash
            log.warning("agent.recall.fetch_failed", error=str(exc))
            prior_sessions = []
    # The disclaimer-branching signal is broader than the recall list
    # above: any prior conversation row counts as "has heard the
    # disclaimer". A transient failure here also degrades to False so
    # the full disclaimer plays — safe default.
    is_returning_user = core_conversations.has_prior_session(user, supabase_token=supabase_token)
    if is_returning_user:
        log.info("agent.disclaimer.short_branch")
    instructions = build_triage_system_prompt(prior_sessions, is_returning_user=is_returning_user)
    agent = build_agent(deps, instructions=instructions)

    _wire_tool_call_forwarding(
        session,
        ctx,
        log,
        conv_id=conv_id,
        deps=deps,
    )
    _wire_metrics_logging(session)
    _wire_safety_screen(session, deps, log, conv_id=conv_id, ctx=ctx)
    if conv_id is not None:
        _wire_conversation_persistence(
            session,
            conv_id=conv_id,
            deps=deps,
            log=log,
        )
        _wire_end_conversation_on_shutdown(
            ctx,
            conv_id=conv_id,
            deps=deps,
            log=log,
        )

    _wire_supabase_token_refresh(ctx.room, deps, log)

    log.info(
        "agent.session.ready",
        worker_id=ctx.worker_id,
        room=ctx.room.name,
        user_id=user_id_str,
        tools=list(TRIAGE_TOOL_NAMES),
    )

    try:
        await session.start(agent, room=ctx.room)
    finally:
        if conv_id is not None and supabase_token is not None:
            try:
                core_conversations.end(conv_id, supabase_token=supabase_token)
                log.info("agent.conversation.ended", conversation_id=str(conv_id))
            except Exception as exc:  # noqa: BLE001 — best-effort summary
                log.warning("agent.conversation.end_failed", error=str(exc))
        # Drop the in-process slot state so a long-running worker does
        # not accumulate state across many sessions.
        core_triage.clear(session_id)
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
    """Build the :class:`WorkerOptions` the CLI uses to register the worker."""
    settings = get_settings()
    return WorkerOptions(
        entrypoint_fnc=entrypoint,
        agent_name=AGENT_NAME,
        ws_url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )


# Suppress unused-import linting on `all_tools` and `dispatch` — they are
# part of the public surface other adapters re-export from this module
# even though the triage entrypoint itself drives tools by name.
_ = all_tools, dispatch


__all__ = [
    "SESSION_END_TOPIC",
    "SYSTEM_PROMPT",
    "TOOL_CALLS_TOPIC",
    "TRIAGE_STATE_TOPIC",
    "TRIAGE_TOOL_NAMES",
    "build_agent",
    "build_session",
    "build_system_prompt",
    "build_triage_system_prompt",
    "entrypoint",
    "worker_options",
]
