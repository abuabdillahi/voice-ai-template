"""Unit tests for `core.realtime`.

These tests pin the kwargs the factory passes to the OpenAI plugin's
``RealtimeModel`` constructor — particularly the new ``turn_detection``
configuration that gates how aggressively the model yields a turn on
incoming audio.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from core import realtime
from core.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        supabase_url="https://test.supabase.co",
        supabase_publishable_key="test-publishable",
        supabase_jwks_url="https://test.supabase.co/auth/v1/.well-known/jwks.json",
        livekit_url="wss://test.livekit.cloud",
        livekit_api_key="lk-test-key",  # pragma: allowlist secret
        livekit_api_secret="lk-test-secret",  # pragma: allowlist secret
        openai_api_key="sk-test-openai",  # pragma: allowlist secret
    )


def test_create_realtime_model_passes_bumped_server_vad_thresholds(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    """The factory configures server VAD with bumped amplitude thresholds.

    Why server VAD and not semantic VAD: the LiveKit plugin docs and
    the OpenAI Realtime API reference both make clear that
    ``eagerness`` on ``semantic_vad`` controls *how quickly the model
    responds* once the user has stopped — a "lets users take their
    time speaking" knob — not the noise-gate threshold that decides
    whether incoming audio counts as speech in the first place.
    Coughs / sighs / keyboard clicks still cross the speech-detection
    line under semantic VAD at any eagerness, which is the symptom
    issue 04 was trying to fix.

    The amplitude gate lives on ``server_vad.threshold`` (0–1, higher
    = less sensitive). Issue 04 names the bumped config as the
    explicit fallback: ``threshold=0.7``, ``silence_duration_ms=800``,
    ``prefix_padding_ms=300``. The thresholds are exposed as module-
    level constants so a future tuning pass is a one-line change
    without re-reading the surrounding factory.
    """
    captured: dict[str, Any] = {}

    def _fake_constructor(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(
        "core.realtime.openai_plugin.realtime.RealtimeModel",
        _fake_constructor,
    )

    realtime.create_realtime_model(settings)

    turn_detection = captured.get("turn_detection")
    assert turn_detection is not None, "turn_detection kwarg must be supplied"

    def _field(name: str) -> Any:
        if isinstance(turn_detection, dict):
            return turn_detection.get(name)
        return getattr(turn_detection, name, None)

    assert _field("type") == "server_vad"
    assert _field("threshold") == 0.7
    assert _field("silence_duration_ms") == 800
    assert _field("prefix_padding_ms") == 300

    # And the constants are exposed for review.
    assert realtime._SERVER_VAD_THRESHOLD == 0.7
    assert realtime._SERVER_VAD_SILENCE_DURATION_MS == 800
    assert realtime._SERVER_VAD_PREFIX_PADDING_MS == 300
