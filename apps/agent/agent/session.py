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
from core.auth import User
from core.config import Settings, get_settings
from core.observability import setup_logging
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
from livekit.agents.voice.events import FunctionToolsExecutedEvent

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
    "When the user states a preference about themselves "
    "(favorite color, preferred name, language, dietary needs, and so on), "
    "call set_preference with a short snake_case key and the stated value. "
    "Before answering personal questions, consider calling get_preference "
    "to recall what they have told you previously."
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


def _resolve_user_from_ctx(ctx: JobContext) -> User:
    """Reconstruct the :class:`User` from the LiveKit token claims.

    The API minted the token with the Supabase user id as the
    participant identity (see :mod:`core.livekit`). The `name` field
    carries the email. We deliberately do not re-verify the JWT here:
    LiveKit has already verified it on join, and the worker's job is
    to act on a participant that has already been admitted.
    """
    claims = ctx.token_claims()
    identity = claims.identity
    name = claims.name or ""
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
        domain_ctx = DomainToolContext(user=deps.user, log=deps.log)
        result = await dispatch(schema_name, raw_arguments, domain_ctx)
        # The realtime model expects a string result. JSON-encode
        # mappings (errors, structured outputs) so the model gets a
        # parseable payload it can verbalise.
        if isinstance(result, str):
            return result
        return json.dumps(result)

    return _invoke


def build_agent(deps: _SessionDeps | None = None) -> Agent:
    """Construct the :class:`Agent` with the system prompt and tools.

    When ``deps`` is omitted, the agent is built without tools (the
    shape the issue-05 unit tests still rely on). The session
    entrypoint always passes ``deps`` so the live agent has tools.
    """
    if deps is None:
        return Agent(instructions=SYSTEM_PROMPT)

    tools = [_make_livekit_tool(schema.name, deps) for schema in all_tools()]
    return Agent(instructions=SYSTEM_PROMPT, tools=list(tools))


def build_session(settings: Settings | None = None) -> AgentSession[None]:
    """Construct the :class:`AgentSession` with the realtime model.

    Factored out so tests can build a session without dispatching a
    real LiveKit job, and so the realtime model factory remains the
    only seam for swapping providers.
    """
    settings = settings or get_settings()
    model = create_realtime_model(settings)
    return AgentSession[None](llm=model)


def _wire_tool_call_forwarding(
    session: AgentSession[None],
    ctx: JobContext,
    log: Any,
) -> None:
    """Subscribe to ``function_tools_executed`` and forward to the room.

    Each completed tool call is emitted as a structured log line and
    sent on the ``lk.tool-calls`` text-stream topic. The frontend
    listens on that topic and renders the calls inline with the
    transcript.
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

    user = _resolve_user_from_ctx(ctx)
    deps = _SessionDeps(user=user, log=log.bind(user_id=str(user.id)))

    session = build_session(settings)
    agent = build_agent(deps)

    _wire_tool_call_forwarding(session, ctx, log)

    log.info(
        "agent.session.ready",
        worker_id=ctx.worker_id,
        room=ctx.room.name,
        user_id=str(user.id),
        tools=[t.name for t in all_tools()],
    )

    await session.start(agent, room=ctx.room)


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
        ws_url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )


__all__ = [
    "SYSTEM_PROMPT",
    "TOOL_CALLS_TOPIC",
    "build_agent",
    "build_session",
    "entrypoint",
    "worker_options",
]
