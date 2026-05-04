"""Realtime model factory.

The voice loop is driven by a speech-to-speech "realtime" model that
both transcribes user audio and produces assistant audio in a single
duplex stream. The default is OpenAI Realtime via the livekit-agents
OpenAI plugin.

`create_realtime_model` is the **single seam** any future provider
plugs into. Subsequent issues swap models by editing this function or
shadowing it in a downstream fork; we deliberately do not build a
config-driven plugin registry here. YAGNI: there is exactly one model
in the template today, and the call site (`agent.session`) is the only
consumer.

The factory returns the abstract `RealtimeModel` base class from
`livekit-agents` so call sites can stay provider-agnostic.
"""

from __future__ import annotations

from typing import Any

from livekit.agents.llm import RealtimeModel
from livekit.plugins import openai as openai_plugin

from core.config import Settings, get_settings

# The default OpenAI realtime model. Pinned by name here so the choice
# is reviewable and so an upgrade is a single-line change.
_DEFAULT_OPENAI_REALTIME_MODEL = "gpt-realtime"


def create_realtime_model(
    settings: Settings | None = None,
    *,
    voice: str | None = None,
) -> RealtimeModel:
    """Build the realtime model used by the agent worker.

    Returns an OpenAI Realtime model wired with the API key from
    settings. The function takes optional `settings` so tests can
    inject a fake; production callers pass nothing and pick up the
    process-wide singleton.

    ``voice`` selects the Realtime model's spoken voice. Issue 10's
    settings page stores this per-user under the ``voice`` preference
    key; the agent worker reads it at session start and threads it
    through here. When ``None``, the underlying plugin's default voice
    is used.
    """
    settings = settings or get_settings()
    kwargs: dict[str, Any] = {
        "model": _DEFAULT_OPENAI_REALTIME_MODEL,
        "api_key": settings.openai_api_key,
    }
    if voice is not None:
        kwargs["voice"] = voice
    return openai_plugin.realtime.RealtimeModel(**kwargs)


__all__ = ["create_realtime_model"]
