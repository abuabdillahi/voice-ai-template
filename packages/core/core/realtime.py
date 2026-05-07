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
from livekit.agents.tts import TTS
from livekit.plugins import openai as openai_plugin

from core.config import Settings, get_settings

# The default OpenAI realtime model. Pinned by name here so the choice
# is reviewable and so an upgrade is a single-line change.
_DEFAULT_OPENAI_REALTIME_MODEL = "gpt-realtime"

# Default voice. Must exist in BOTH the gpt-realtime catalog and the
# gpt-4o-mini-tts catalog so the realtime model and the safety-TTS
# share a voice — otherwise the safety script sounds like it comes
# from a different system. Overlapping set: alloy, ash, ballad, coral,
# sage, shimmer, verse. Realtime-only voices (marin, cedar) are off
# limits because the TTS plugin would error at speak time.
_DEFAULT_VOICE = "sage"

# Server-VAD threshold tuning. We use server_vad rather than
# semantic_vad because the LiveKit and OpenAI Realtime docs both make
# clear that ``eagerness`` on ``semantic_vad`` controls *how quickly
# the model responds once the user has stopped* (a "lets users take
# their time speaking" knob), not the amplitude noise-gate that
# decides whether incoming audio counts as speech in the first place.
# Coughs, sighs, throat-clears, and keyboard clicks still cross the
# speech-detection line under semantic VAD at any eagerness setting,
# which is exactly the symptom issue 04 was trying to fix.
#
# server_vad exposes a direct amplitude gate via ``threshold`` (0–1,
# higher = less sensitive). Pairing a bumped threshold with a longer
# ``silence_duration_ms`` lets transient sounds pass without yielding
# the turn while still allowing a softly-spoken interruption.
#
# Pre-implementation check (issue 04): the installed
# ``livekit-agents`` OpenAI plugin surfaces ``turn_detection`` as a
# constructor kwarg on ``RealtimeModel`` (see
# ``.venv/.../livekit/plugins/openai/realtime/realtime_model.py``,
# overload signatures around line 278). The dict shape we pass is
# coerced into the OpenAI ``ServerVad`` Pydantic model on the wire.
#
# Each value is its own module-level constant so a future tuning
# pass is a one-line change without re-reading the surrounding code.
_SERVER_VAD_THRESHOLD = 0.7
_SERVER_VAD_SILENCE_DURATION_MS = 800
_SERVER_VAD_PREFIX_PADDING_MS = 300


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
        "voice": voice if voice is not None else _DEFAULT_VOICE,
        "turn_detection": {
            "type": "server_vad",
            "threshold": _SERVER_VAD_THRESHOLD,
            "silence_duration_ms": _SERVER_VAD_SILENCE_DURATION_MS,
            "prefix_padding_ms": _SERVER_VAD_PREFIX_PADDING_MS,
        },
    }
    return openai_plugin.realtime.RealtimeModel(**kwargs)


def create_safety_tts(
    settings: Settings | None = None,
    *,
    voice: str | None = None,
) -> TTS[Any]:
    """Build the TTS attached to the AgentSession for safety scripts.

    The realtime model is speech-to-speech and has no separate TTS
    pipeline, so ``AgentSession.say(text)`` raises with "no TTS model".
    Attaching a real TTS makes ``say()`` work, which is what the safety
    hook needs to play the versioned escalation script verbatim — the
    earlier ``generate_reply(instructions=...)`` fallback raced with
    the realtime model's in-flight reply and let the model paraphrase.
    This TTS only fires on safety escalations (rare).

    ``voice`` must match the realtime model's voice so the safety
    script doesn't sound like it comes from a different speaker. The
    caller (``build_session``) threads the same voice into both
    factories. Pass a value from the overlapping set (alloy, ash,
    ballad, coral, sage, shimmer, verse) — realtime-only voices
    (marin, cedar) will error at speak time.
    """
    settings = settings or get_settings()
    return openai_plugin.TTS(
        api_key=settings.openai_api_key,
        voice=voice if voice is not None else _DEFAULT_VOICE,
    )


__all__ = ["create_realtime_model", "create_safety_tts", "DEFAULT_VOICE"]


# Public alias of the module-private default — exposed so call sites
# (chiefly ``build_session``) can resolve ``voice=None`` to the same
# value that goes into both the realtime model and the safety TTS.
DEFAULT_VOICE = _DEFAULT_VOICE
