"""LiveKit Agents entrypoint for the voice loop.

The worker is dispatched into a room by LiveKit, joins it, builds an
:class:`AgentSession` with the configured realtime model, and runs
until the room closes. There is no business logic here yet — the only
behaviour is "be a helpful conversational assistant" via the system
prompt. Issues 06+ extend this entrypoint with tools and memory.

Boundaries:

- This module imports `core.realtime` for the model factory and
  `core.config` / `core.observability` for settings + logging.
- Everything LiveKit-specific (`JobContext`, `AgentSession`,
  `WorkerOptions`) lives only in adapters: this module and
  ``__main__``.
"""

from __future__ import annotations

import structlog
from core.config import Settings, get_settings
from core.observability import setup_logging
from core.realtime import create_realtime_model
from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions

# The hardcoded system prompt for the tracer slice. Subsequent issues
# move this into a versioned prompt file and add tool/memory
# instructions. For the demo it stays inline so the prompt changes
# show up in code review at the entrypoint.
SYSTEM_PROMPT = (
    "You are a helpful conversational assistant. "
    "Keep responses brief and natural for a spoken conversation."
)


def build_agent() -> Agent:
    """Construct the :class:`Agent` with the tracer-slice system prompt.

    Split out of :func:`entrypoint` so unit tests can assert the
    instructions and toolset without spinning up an :class:`AgentSession`.
    """
    return Agent(instructions=SYSTEM_PROMPT)


def build_session(settings: Settings | None = None) -> AgentSession[None]:
    """Construct the :class:`AgentSession` with the realtime model.

    Factored out so tests can build a session without dispatching a
    real LiveKit job, and so the realtime model factory remains the
    only seam for swapping providers.
    """
    settings = settings or get_settings()
    model = create_realtime_model(settings)
    return AgentSession[None](llm=model)


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

    session = build_session(settings)
    agent = build_agent()

    log.info(
        "agent.session.ready",
        worker_id=ctx.worker_id,
        room=ctx.room.name,
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
    "build_agent",
    "build_session",
    "entrypoint",
    "worker_options",
]
