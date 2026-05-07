"""Unit tests for :mod:`core.escalation`.

The coordinator is the state machine that runs the deterministic
teardown when either escalation path fires. Tests exercise the path
sequencing and the shared-guard idempotency without standing up
LiveKit, FastAPI, or a real database.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch
from uuid import UUID

import pytest
from core import safety as _safety
from core.auth import User
from core.escalation import EscalationCoordinator, EscalationGuard


class _RecordingLog:
    """Minimal structlog-shaped sink that captures call args."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, Any]]] = []

    def info(self, name: str, **kwargs: Any) -> None:
        self.events.append(("info", name, kwargs))

    def warning(self, name: str, **kwargs: Any) -> None:
        self.events.append(("warning", name, kwargs))


def _user() -> User:
    return User(id=UUID("11111111-1111-1111-1111-111111111111"), email="alice@example.com")


def _build(**overrides: Any) -> tuple[EscalationCoordinator, dict[str, list[Any]]]:
    """Build a coordinator with recording adapters."""
    spoken: list[tuple[str, str]] = []
    emitted: list[str] = []
    deleted: list[None] = []

    async def _speak(script: str, tier: str) -> None:
        spoken.append((script, tier))

    async def _emit(tier: str) -> None:
        emitted.append(tier)

    async def _delete() -> None:
        deleted.append(None)

    log = _RecordingLog()
    defaults: dict[str, Any] = {
        "log": log,
        "user": _user(),
        "session_id": "test-session",
        "conv_id": UUID("33333333-3333-3333-3333-333333333333"),
        "supabase_token": "tok",
        "guard": EscalationGuard(),
        "speak_script": _speak,
        "emit_session_end": _emit,
        "delete_room": _delete,
        "grace_seconds": 0.0,
        "audio_drain_seconds": 0.0,
    }
    defaults.update(overrides)
    coord = EscalationCoordinator(**defaults)
    sinks = {
        "spoken": spoken,
        "emitted": emitted,
        "deleted": deleted,
        "log": log.events,  # type: ignore[dict-item]
    }
    return coord, sinks


@pytest.mark.asyncio
async def test_classifier_path_runs_full_teardown_in_order() -> None:
    coord, sinks = _build()
    result = _safety.RedFlagResult(
        tier=_safety.RedFlagTier.EMERGENT,
        source="regex",
        matched_flags=("chest_pain",),
    )
    with patch("core.safety_events.record") as record:
        await coord.handle_classifier_result(result, "crushing chest pain")

    assert record.call_count == 1
    assert sinks["spoken"] == [
        (_safety.escalation_script_for(_safety.RedFlagTier.EMERGENT), "emergent")
    ]
    assert sinks["emitted"] == ["emergent"]
    assert sinks["deleted"] == [None]


@pytest.mark.asyncio
async def test_classifier_path_noop_below_urgent() -> None:
    coord, sinks = _build()
    result = _safety.RedFlagResult(tier=_safety.RedFlagTier.NONE, source="regex")
    with patch("core.safety_events.record") as record:
        await coord.handle_classifier_result(result, "totally fine")
    assert record.call_count == 0
    assert sinks["spoken"] == []
    assert sinks["emitted"] == []
    assert sinks["deleted"] == []


@pytest.mark.asyncio
async def test_classifier_path_bails_when_guard_already_claimed() -> None:
    guard = EscalationGuard()
    guard.claim()  # simulate the model path won the race
    coord, sinks = _build(guard=guard)
    result = _safety.RedFlagResult(tier=_safety.RedFlagTier.URGENT, source="regex")
    with patch("core.safety_events.record") as record:
        await coord.handle_classifier_result(result, "concerning utterance")

    assert record.call_count == 0
    assert sinks["spoken"] == []
    assert sinks["emitted"] == []
    assert sinks["deleted"] == []
    # The bail is observable as an info log line for postmortems.
    assert any(name == "agent.safety.guard_taken" for _, name, _ in sinks["log"])


@pytest.mark.asyncio
async def test_model_path_runs_persist_emit_delete_without_speaking() -> None:
    coord, sinks = _build()
    waited: list[None] = []

    async def _wait() -> None:
        waited.append(None)

    with patch("core.safety_events.record") as record:
        await coord.handle_model_escalation("emergent", "user reported chest pain", _wait)

    assert waited == [None]  # waited for in-flight playout
    assert record.call_count == 1
    assert sinks["spoken"] == []  # model already spoke its own version
    assert sinks["emitted"] == ["emergent"]
    assert sinks["deleted"] == [None]


@pytest.mark.asyncio
async def test_model_path_skips_clinician_soon() -> None:
    coord, sinks = _build()
    with patch("core.safety_events.record") as record:
        await coord.handle_model_escalation("clinician_soon", "schedule routine", None)
    assert record.call_count == 0
    assert sinks["emitted"] == []
    assert sinks["deleted"] == []


@pytest.mark.asyncio
async def test_shared_guard_makes_teardown_at_most_once() -> None:
    """Both paths sharing a guard => only the first one runs the tail."""
    guard = EscalationGuard()
    coord_a, sinks_a = _build(guard=guard)
    coord_b, sinks_b = _build(guard=guard)

    result = _safety.RedFlagResult(tier=_safety.RedFlagTier.EMERGENT, source="regex")
    with patch("core.safety_events.record"):
        await coord_a.handle_classifier_result(result, "first")
        await coord_b.handle_model_escalation("emergent", "second", None)

    # First path took the guard and ran teardown.
    assert sinks_a["emitted"] == ["emergent"]
    # Second path bailed.
    assert sinks_b["emitted"] == []
    assert sinks_b["spoken"] == []
    assert sinks_b["deleted"] == []


@pytest.mark.asyncio
async def test_persist_skipped_without_conv_id() -> None:
    coord, sinks = _build(conv_id=None)
    result = _safety.RedFlagResult(tier=_safety.RedFlagTier.EMERGENT, source="regex")
    with patch("core.safety_events.record") as record:
        await coord.handle_classifier_result(result, "...")
    assert record.call_count == 0
    # But the script still plays and the room still tears down.
    assert sinks["spoken"] != []
    assert sinks["deleted"] == [None]
