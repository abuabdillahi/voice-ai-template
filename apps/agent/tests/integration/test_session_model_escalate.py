"""Integration-style tests for the model-initiated escalate hook.

Issue 02 — when the realtime model calls ``escalate(tier='emergent' |
'urgent', reason=...)``, the agent worker waits for the model's
spoken response to that turn to finish playing out, then runs the
same teardown sequence the safety screen runs (persist → emit
session-end → delete room). When ``tier='clinician_soon'`` the
conversation continues; no teardown runs.

A session-scoped idempotency guard prevents the safety-screen and
the model-initiated paths from both running teardown when both fire
on the same turn.

Per the established pattern in :mod:`test_session_safety`, this test
suite drives the wiring helpers against tiny fakes rather than
standing up the LiveKit voice loop.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID

import pytest
from agent.session import _SessionDeps
from core import safety
from core.auth import User
from core.config import Settings


@pytest.fixture(autouse=True)
def _silent_classifier(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the classifier and pin the settings cache so the safety screen
    does not reach for live OpenAI / Supabase credentials.
    """

    async def _stub(_utterance: str, *, settings: Any | None = None) -> safety.RedFlagResult:
        return safety.RedFlagResult(tier=safety.RedFlagTier.NONE, source="classifier")

    monkeypatch.setattr("agent.session.core_safety.classify", _stub)
    # Default the model-grace window to zero across this file so tests
    # that aren't probing the grace behaviour itself don't pay 0.3s of
    # wallclock each. The two grace-window tests below override this.
    monkeypatch.setattr("agent.session._ESCALATION_MODEL_GRACE_SECONDS", 0.0)
    fake = Settings(
        supabase_url="https://test.supabase.co",
        supabase_publishable_key="test-publishable",
        supabase_jwks_url="https://test.supabase.co/auth/v1/.well-known/jwks.json",
        livekit_url="wss://test.livekit.cloud",
        livekit_api_key="lk-test-key",  # pragma: allowlist secret
        livekit_api_secret="lk-test-secret",  # pragma: allowlist secret
        openai_api_key="sk-test-openai",  # pragma: allowlist secret
    )
    monkeypatch.setattr("agent.session.get_settings", lambda: fake)


class _RecordingLogger:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def _record(self, level: str, event: str, **kwargs: Any) -> None:
        self.records.append({"_level": level, "event": event, **kwargs})

    def warning(self, event: str, **kwargs: Any) -> None:
        self._record("warning", event, **kwargs)

    def info(self, event: str, **kwargs: Any) -> None:
        self._record("info", event, **kwargs)

    def bind(self, **_kwargs: Any) -> _RecordingLogger:
        return self


class _FakeSession:
    def __init__(self) -> None:
        self.listeners: dict[str, list[Any]] = {}
        self.said: list[str] = []
        self.interrupted = 0

    def on(self, event: str, handler: Any) -> None:
        self.listeners.setdefault(event, []).append(handler)

    async def say(self, text: str) -> None:
        self.said.append(text)

    async def interrupt(self) -> None:
        self.interrupted += 1


class _FakeSpeechHandle:
    def __init__(self, *, timeline: list[str] | None = None, label: str = "model_turn") -> None:
        self._timeline = timeline
        self._label = label
        self.played_out = False
        self.wait_calls = 0

    async def wait_for_playout(self) -> None:
        self.wait_calls += 1
        # Yield once to allow other tasks to interleave so a test that
        # races teardown against another path can observe ordering.
        await asyncio.sleep(0)
        self.played_out = True
        if self._timeline is not None:
            self._timeline.append(f"playout:{self._label}")


class _FakeSpeechCreatedEvent:
    def __init__(self, handle: _FakeSpeechHandle, *, user_initiated: bool = False) -> None:
        self.speech_handle = handle
        self.user_initiated = user_initiated
        self.source = "generate_reply"


class _FakeFunctionCall:
    def __init__(self, *, name: str, arguments: str, call_id: str = "call-1") -> None:
        self.name = name
        self.arguments = arguments
        self.call_id = call_id


class _FakeFunctionToolsExecutedEvent:
    def __init__(self, calls: list[_FakeFunctionCall], outputs: list[Any] | None = None) -> None:
        self._calls = calls
        self._outputs = outputs if outputs is not None else [None] * len(calls)

    def zipped(self) -> list[tuple[_FakeFunctionCall, Any]]:
        return list(zip(self._calls, self._outputs, strict=False))


class _RoomFake:
    def __init__(self, *, name: str = "user-abc", timeline: list[str] | None = None) -> None:
        self.sent: list[dict[str, Any]] = []
        self.local_participant = self
        self.name = name
        self._timeline = timeline

    async def send_text(self, payload: str, *, topic: str) -> None:
        self.sent.append({"topic": topic, "payload": payload})
        if self._timeline is not None:
            self._timeline.append(f"send_text:{topic}")


class _JobCtxFake:
    def __init__(self, room: _RoomFake) -> None:
        self.room = room


def _deps(token: str | None = "user-jwt") -> _SessionDeps:
    return _SessionDeps(
        user=User(id=UUID("11111111-1111-1111-1111-111111111111"), email="alice@example.com"),
        log=_RecordingLogger(),
        session_id="user-abc",
        supabase_access_token=token,
    )


def _fire_speech_created(session: _FakeSession, event: _FakeSpeechCreatedEvent) -> None:
    for handler in session.listeners.get("speech_created", []):
        handler(event)


def _fire_function_tools_executed(
    session: _FakeSession, event: _FakeFunctionToolsExecutedEvent
) -> None:
    for handler in session.listeners.get("function_tools_executed", []):
        handler(event)


def _fire_conversation_item_added(session: _FakeSession, event: Any) -> None:
    for handler in session.listeners.get("conversation_item_added", []):
        handler(event)


async def _drain() -> None:
    for _ in range(50):
        await asyncio.sleep(0)


def _escalate_call(
    *, tier: str, reason: str = "model judged escalation warranted"
) -> _FakeFunctionCall:
    return _FakeFunctionCall(
        name="escalate",
        arguments=json.dumps({"tier": tier, "reason": reason}),
    )


# ---------------------------------------------------------------------------
# Tier-1 / Tier-2 — teardown runs after the model finishes speaking.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tier1_model_escalate_runs_teardown_after_speech_playout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent.session import (
        SESSION_END_TOPIC,
        EscalationGuard,
        _wire_model_escalate_teardown,
    )

    persists: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "agent.session.core_safety_events.record",
        lambda *args, **kwargs: persists.append({"args": args, "kwargs": kwargs}),
    )
    delete_calls: list[str] = []

    async def _fake_delete(room_name: str, *, log: Any) -> None:
        delete_calls.append(room_name)

    monkeypatch.setattr("agent.session._delete_room_after_drain", _fake_delete)

    session = _FakeSession()
    log = _RecordingLogger()
    deps = _deps()
    room = _RoomFake()
    ctx = _JobCtxFake(room)
    guard = EscalationGuard()

    _wire_model_escalate_teardown(
        session,
        deps,
        log,
        conv_id=UUID("33333333-3333-3333-3333-333333333333"),
        ctx=ctx,
        guard=guard,
    )

    # The realtime model emits a speech_created event for the assistant
    # turn that contains the escalate tool call; then the tool executes.
    handle = _FakeSpeechHandle()
    _fire_speech_created(session, _FakeSpeechCreatedEvent(handle))
    _fire_function_tools_executed(
        session,
        _FakeFunctionToolsExecutedEvent([_escalate_call(tier="emergent")]),
    )
    await _drain()

    # The model's speech handle was awaited via wait_for_playout — not a
    # fixed sleep — so the agent worker only acts after the audio has
    # finished playing.
    assert handle.wait_calls == 1, (
        "the agent worker must call SpeechHandle.wait_for_playout() exactly once "
        f"per model-initiated escalate; got {handle.wait_calls}"
    )

    # Teardown ran: the safety_events row was persisted with source='model',
    # the session-end signal was emitted, and the room was deleted.
    assert len(persists) == 1, f"exactly one safety_events row must be persisted; got {persists}"
    args = persists[0]["args"]
    assert args[2] == "emergent"  # tier
    assert args[3] == "model"  # source

    end_signals = [s for s in room.sent if s["topic"] == SESSION_END_TOPIC]
    assert end_signals, "session-end signal must be emitted on lk.session-end"
    payload = json.loads(end_signals[0]["payload"])
    assert payload == {"reason": "escalation", "tier": "emergent"}

    assert delete_calls == [
        room.name
    ], f"the LiveKit room must be deleted with the room name; got {delete_calls}"


@pytest.mark.asyncio
async def test_tier2_model_escalate_runs_teardown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent.session import (
        SESSION_END_TOPIC,
        EscalationGuard,
        _wire_model_escalate_teardown,
    )

    persists: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "agent.session.core_safety_events.record",
        lambda *args, **kwargs: persists.append({"args": args, "kwargs": kwargs}),
    )

    async def _fake_delete(_room_name: str, *, log: Any) -> None:
        return None

    monkeypatch.setattr("agent.session._delete_room_after_drain", _fake_delete)

    session = _FakeSession()
    log = _RecordingLogger()
    deps = _deps()
    room = _RoomFake()
    ctx = _JobCtxFake(room)
    guard = EscalationGuard()

    _wire_model_escalate_teardown(
        session,
        deps,
        log,
        conv_id=UUID("33333333-3333-3333-3333-333333333333"),
        ctx=ctx,
        guard=guard,
    )

    handle = _FakeSpeechHandle()
    _fire_speech_created(session, _FakeSpeechCreatedEvent(handle))
    _fire_function_tools_executed(
        session,
        _FakeFunctionToolsExecutedEvent([_escalate_call(tier="urgent")]),
    )
    await _drain()

    assert len(persists) == 1
    assert persists[0]["args"][2] == "urgent"
    end_signals = [s for s in room.sent if s["topic"] == SESSION_END_TOPIC]
    assert end_signals
    assert json.loads(end_signals[0]["payload"]) == {"reason": "escalation", "tier": "urgent"}


@pytest.mark.asyncio
async def test_tier3_model_escalate_does_not_run_teardown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``clinician_soon`` keeps the conversation alive — no teardown.

    AC: "no teardown runs — the conversation continues as it does
    today, so the user can still ask follow-up questions about
    scheduling care."
    """
    from agent.session import (
        SESSION_END_TOPIC,
        EscalationGuard,
        _wire_model_escalate_teardown,
    )

    persists: list[Any] = []
    monkeypatch.setattr(
        "agent.session.core_safety_events.record",
        lambda *args, **kwargs: persists.append((args, kwargs)),
    )
    delete_calls: list[str] = []

    async def _fake_delete(room_name: str, *, log: Any) -> None:
        delete_calls.append(room_name)

    monkeypatch.setattr("agent.session._delete_room_after_drain", _fake_delete)

    session = _FakeSession()
    log = _RecordingLogger()
    deps = _deps()
    room = _RoomFake()
    ctx = _JobCtxFake(room)
    guard = EscalationGuard()

    _wire_model_escalate_teardown(
        session,
        deps,
        log,
        conv_id=UUID("33333333-3333-3333-3333-333333333333"),
        ctx=ctx,
        guard=guard,
    )

    handle = _FakeSpeechHandle()
    _fire_speech_created(session, _FakeSpeechCreatedEvent(handle))
    _fire_function_tools_executed(
        session,
        _FakeFunctionToolsExecutedEvent([_escalate_call(tier="clinician_soon")]),
    )
    await _drain()

    assert persists == []
    assert delete_calls == []
    assert [s for s in room.sent if s["topic"] == SESSION_END_TOPIC] == []
    # The guard remains unclaimed so a later genuine escalation can
    # still take it — the clinician_soon branch must not consume the
    # session-scoped guard.
    assert guard.fired is False


@pytest.mark.asyncio
async def test_model_escalate_persisted_row_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """source='model', matched_flags=[], utterance='' on the persisted row.

    The free-text ``reason`` lives in structured logs only. Putting it
    on ``matched_flags`` would conflate model-supplied prose with the
    canonical flag id taxonomy used by the regex / classifier layers.
    """
    from agent.session import EscalationGuard, _wire_model_escalate_teardown

    captured: list[dict[str, Any]] = []

    def _fake_record(
        conversation_id: UUID,
        user_id: UUID,
        tier: str,
        source: str,
        matched_flags: Any,
        utterance: str,
        *,
        supabase_token: str,
    ) -> Any:
        captured.append(
            {
                "conversation_id": conversation_id,
                "user_id": user_id,
                "tier": tier,
                "source": source,
                "matched_flags": list(matched_flags),
                "utterance": utterance,
                "supabase_token": supabase_token,
            }
        )
        return object()

    monkeypatch.setattr("agent.session.core_safety_events.record", _fake_record)

    async def _no_delete(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr("agent.session._delete_room_after_drain", _no_delete)

    session = _FakeSession()
    log = _RecordingLogger()
    deps = _deps()
    room = _RoomFake()
    ctx = _JobCtxFake(room)
    guard = EscalationGuard()
    conv_id = UUID("33333333-3333-3333-3333-333333333333")

    _wire_model_escalate_teardown(session, deps, log, conv_id=conv_id, ctx=ctx, guard=guard)

    handle = _FakeSpeechHandle()
    _fire_speech_created(session, _FakeSpeechCreatedEvent(handle))
    _fire_function_tools_executed(
        session,
        _FakeFunctionToolsExecutedEvent(
            [_escalate_call(tier="emergent", reason="user said cardiac arrest")]
        ),
    )
    await _drain()

    assert len(captured) == 1
    row = captured[0]
    assert row["conversation_id"] == conv_id
    assert row["user_id"] == deps.user.id
    assert row["tier"] == "emergent"
    assert row["source"] == "model"
    assert row["matched_flags"] == []
    assert row["utterance"] == ""
    assert row["supabase_token"] == "user-jwt"

    # The reason landed in structured logs, on the escalation event line.
    escalation_lines = [r for r in log.records if r.get("event") == "agent.safety.escalation"]
    assert escalation_lines
    line = escalation_lines[0]
    assert line["source"] == "model"
    assert line["tier"] == "emergent"
    assert line["matched_flags"] == []
    assert line["reason"] == "user said cardiac arrest"


# ---------------------------------------------------------------------------
# Idempotency — safety screen and model path race on the same turn.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_safety_screen_wins_race_model_path_bails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Safety screen claims the guard first; model path observes and bails.

    AC: "If the safety-screen path wins the race, the model-initiated
    path observes the guard and bails (logs a structured event but
    does not re-emit the signal, re-persist, or re-attempt deletion)."

    Sharing one :class:`EscalationGuard` between the two wired hooks
    is the seam — both paths consult the same guard before any
    persist / signal / delete side-effect.
    """
    from agent.session import (
        SESSION_END_TOPIC,
        EscalationGuard,
        _wire_model_escalate_teardown,
    )

    persists: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "agent.session.core_safety_events.record",
        lambda *args, **kwargs: persists.append({"args": args, "kwargs": kwargs}),
    )
    delete_calls: list[str] = []

    async def _fake_delete(room_name: str, *, log: Any) -> None:
        delete_calls.append(room_name)

    monkeypatch.setattr("agent.session._delete_room_after_drain", _fake_delete)

    session = _FakeSession()
    log = _RecordingLogger()
    deps = _deps()
    room = _RoomFake()
    ctx = _JobCtxFake(room)
    guard = EscalationGuard()

    # Simulate the safety-screen path having already claimed the guard
    # (its persist + speak + signal + delete already fired upstream of
    # this hook in the real flow).
    assert guard.claim() is True

    _wire_model_escalate_teardown(
        session,
        deps,
        log,
        conv_id=UUID("33333333-3333-3333-3333-333333333333"),
        ctx=ctx,
        guard=guard,
    )

    handle = _FakeSpeechHandle()
    _fire_speech_created(session, _FakeSpeechCreatedEvent(handle))
    _fire_function_tools_executed(
        session,
        _FakeFunctionToolsExecutedEvent([_escalate_call(tier="emergent")]),
    )
    await _drain()

    # The model path bailed — no persist, no signal, no delete.
    assert persists == []
    assert delete_calls == []
    assert [s for s in room.sent if s["topic"] == SESSION_END_TOPIC] == []
    # And it logged a structured bail event so the race is observable
    # in production logs.
    bail_lines = [
        r for r in log.records if r.get("event") == "agent.safety.model_escalate.guard_taken"
    ]
    assert bail_lines, "model path must log a structured bail when the guard is already taken"
    assert bail_lines[0]["tier"] == "emergent"


@pytest.mark.asyncio
async def test_model_path_wins_race_safety_screen_bails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Model path claims the guard first; safety-screen path observes and bails.

    The safety-screen hook (:func:`agent.session._wire_safety_screen`)
    must accept and consult the same :class:`EscalationGuard` so a
    later regex+classifier hit on the next user utterance does not
    re-run teardown.
    """
    from agent.session import (
        SESSION_END_TOPIC,
        EscalationGuard,
        _wire_safety_screen,
    )

    persists: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "agent.session.core_safety_events.record",
        lambda *args, **kwargs: persists.append({"args": args, "kwargs": kwargs}),
    )
    delete_calls: list[str] = []

    async def _fake_delete(room_name: str, *, log: Any) -> None:
        delete_calls.append(room_name)

    monkeypatch.setattr("agent.session._delete_room_after_drain", _fake_delete)

    session = _FakeSession()
    log = _RecordingLogger()
    deps = _deps()
    room = _RoomFake()
    ctx = _JobCtxFake(room)
    guard = EscalationGuard()

    # Model path already claimed the guard upstream.
    assert guard.claim() is True

    _wire_safety_screen(
        session,
        deps,
        log,
        conv_id=UUID("33333333-3333-3333-3333-333333333333"),
        ctx=ctx,
        guard=guard,
    )

    # A regex tier-1 utterance arrives after the model has already won.
    class _Item:
        def __init__(self, *, role: str, text: str, item_id: str) -> None:
            self.role = role
            self._text = text
            self.id = item_id

        def text_content(self) -> str:
            return self._text

    class _Event:
        def __init__(self, item: _Item) -> None:
            self.item = item

    _fire_conversation_item_added(
        session, _Event(_Item(role="user", text="I am having chest pain", item_id="i-1"))
    )
    await _drain()

    # The safety screen observed the taken guard and bailed.
    assert persists == []
    assert delete_calls == []
    assert [s for s in room.sent if s["topic"] == SESSION_END_TOPIC] == []
    assert session.said == [], (
        "the safety screen must NOT speak the script when the guard is already taken; "
        f"got said={session.said}"
    )
    bail_lines = [r for r in log.records if r.get("event") == "agent.safety.guard_taken"]
    assert bail_lines, "safety screen must log a structured bail when the guard is already taken"


# ---------------------------------------------------------------------------
# Speech-handle ordering — teardown must follow ``wait_for_playout``.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_teardown_runs_after_speech_handle_playout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The persist / signal / delete sequence must follow speech playout.

    AC: "The model finished-speaking signal is taken from the realtime
    framework's ``speech_created`` event and the resulting
    ``SpeechHandle.wait_for_playout()``, not a fixed sleep." This
    test pins the ordering by sharing a timeline list between the
    fake speech handle and the fake room: the playout marker must
    precede every teardown side-effect.
    """
    from agent.session import (
        SESSION_END_TOPIC,
        EscalationGuard,
        _wire_model_escalate_teardown,
    )

    timeline: list[str] = []
    monkeypatch.setattr(
        "agent.session.core_safety_events.record",
        lambda *args, **kwargs: timeline.append("persist"),
    )

    async def _fake_delete(_room_name: str, *, log: Any) -> None:
        timeline.append("delete_room")

    monkeypatch.setattr("agent.session._delete_room_after_drain", _fake_delete)

    session = _FakeSession()
    log = _RecordingLogger()
    deps = _deps()
    room = _RoomFake(timeline=timeline)
    ctx = _JobCtxFake(room)
    guard = EscalationGuard()

    _wire_model_escalate_teardown(
        session,
        deps,
        log,
        conv_id=UUID("33333333-3333-3333-3333-333333333333"),
        ctx=ctx,
        guard=guard,
    )

    handle = _FakeSpeechHandle(timeline=timeline, label="model_turn")
    _fire_speech_created(session, _FakeSpeechCreatedEvent(handle))
    _fire_function_tools_executed(
        session,
        _FakeFunctionToolsExecutedEvent([_escalate_call(tier="emergent")]),
    )
    await _drain()

    # The handle's playout marker must precede every teardown event.
    playout_idx = timeline.index("playout:model_turn")
    persist_idx = timeline.index("persist")
    signal_idx = timeline.index(f"send_text:{SESSION_END_TOPIC}")
    delete_idx = timeline.index("delete_room")
    assert (
        playout_idx < persist_idx
    ), f"persist must run after speech playout; got timeline={timeline}"
    assert (
        playout_idx < signal_idx
    ), f"session-end signal must be emitted after speech playout; got timeline={timeline}"
    assert (
        playout_idx < delete_idx
    ), f"room delete must run after speech playout; got timeline={timeline}"


@pytest.mark.asyncio
async def test_model_path_does_not_speak_or_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The model-initiated path trusts the model's voice — the worker stays silent.

    AC: "The model's spoken reply is not interrupted or re-spoken by
    the agent worker — we trust the model to read the script from the
    tool-call result." Concretely, the model-escalate hook must not
    call ``session.say`` or ``session.interrupt``; the model already
    spoke the script for that turn.
    """
    from agent.session import EscalationGuard, _wire_model_escalate_teardown

    monkeypatch.setattr("agent.session.core_safety_events.record", lambda *a, **k: None)

    async def _no_delete(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr("agent.session._delete_room_after_drain", _no_delete)

    session = _FakeSession()
    log = _RecordingLogger()
    deps = _deps()
    room = _RoomFake()
    ctx = _JobCtxFake(room)
    guard = EscalationGuard()

    _wire_model_escalate_teardown(
        session,
        deps,
        log,
        conv_id=UUID("33333333-3333-3333-3333-333333333333"),
        ctx=ctx,
        guard=guard,
    )

    handle = _FakeSpeechHandle()
    _fire_speech_created(session, _FakeSpeechCreatedEvent(handle))
    _fire_function_tools_executed(
        session,
        _FakeFunctionToolsExecutedEvent([_escalate_call(tier="emergent")]),
    )
    await _drain()

    assert session.said == [], "model path must not call session.say"
    assert session.interrupted == 0, "model path must not call session.interrupt"


# ---------------------------------------------------------------------------
# Grace window — the safety screen waits briefly before claiming so the
# realtime model can call `escalate` itself and own the script speak.
# ---------------------------------------------------------------------------


def _user_item_event(text: str, item_id: str = "i-1") -> Any:
    """Build a fake conversation_item_added event with a user item."""

    class _Item:
        def __init__(self, *, role: str, body: str, ident: str) -> None:
            self.role = role
            self._text = body
            self.id = ident

        def text_content(self) -> str:
            return self._text

    class _Event:
        def __init__(self, item: _Item) -> None:
            self.item = item

    return _Event(_Item(role="user", body=text, ident=item_id))


@pytest.mark.asyncio
async def test_grace_window_lets_model_claim_first_and_screen_bails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """During the grace window the model can call ``escalate`` and claim
    the guard first; the safety screen observes the take, bails, and —
    crucially — does not interrupt the model or speak the script.

    With ``_ESCALATION_MODEL_GRACE_SECONDS=0`` this property could not
    hold: the screen's claim is sub-millisecond and would always beat
    the model's speech-to-tool-call latency. The grace window is what
    makes the model-wins-natural-races case observable.
    """
    from agent.session import (
        SESSION_END_TOPIC,
        EscalationGuard,
        _wire_model_escalate_teardown,
        _wire_safety_screen,
    )

    # Restore a real grace window — long enough that the model's task
    # runs during it. The autouse fixture pinned it to 0.0.
    monkeypatch.setattr("agent.session._ESCALATION_MODEL_GRACE_SECONDS", 0.1)

    persists: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "agent.session.core_safety_events.record",
        lambda *args, **kwargs: persists.append({"args": args, "kwargs": kwargs}),
    )
    delete_calls: list[str] = []

    async def _fake_delete(room_name: str, *, log: Any) -> None:
        delete_calls.append(room_name)

    monkeypatch.setattr("agent.session._delete_room_after_drain", _fake_delete)

    session = _FakeSession()
    log = _RecordingLogger()
    deps = _deps()
    room = _RoomFake()
    ctx = _JobCtxFake(room)
    guard = EscalationGuard()
    conv_id = UUID("33333333-3333-3333-3333-333333333333")

    _wire_safety_screen(session, deps, log, conv_id=conv_id, ctx=ctx, guard=guard)
    _wire_model_escalate_teardown(session, deps, log, conv_id=conv_id, ctx=ctx, guard=guard)

    # User finalises a tier-1 utterance → safety screen task starts and
    # enters its grace-window sleep.
    _fire_conversation_item_added(session, _user_item_event("I am having chest pain"))
    # Yield long enough for the regex/classifier gather to resolve and
    # the screen task to be parked in its grace sleep — but well below
    # the 0.1s grace window.
    await asyncio.sleep(0.02)

    # Model emits the escalate tool call during the grace window.
    handle = _FakeSpeechHandle()
    _fire_speech_created(session, _FakeSpeechCreatedEvent(handle))
    _fire_function_tools_executed(
        session,
        _FakeFunctionToolsExecutedEvent([_escalate_call(tier="emergent")]),
    )

    # Wait past the grace window so the screen's task wakes, observes
    # the taken guard, and bails.
    await asyncio.sleep(0.2)
    await _drain()

    # Exactly one teardown ran — the model's.
    assert len(persists) == 1, f"exactly one safety_events row expected; got {len(persists)}"
    # Position 3 in core_safety_events.record's positional args is `source`.
    assert persists[0]["args"][3] == "model"
    assert delete_calls == [room.name]
    sent_signals = [s for s in room.sent if s["topic"] == SESSION_END_TOPIC]
    assert len(sent_signals) == 1, "exactly one session-end signal must be emitted"

    # The screen stayed silent — no script spoken, no interrupt issued.
    assert session.said == [], (
        "safety screen must not speak the script when the model wins the grace race; "
        f"got said={session.said}"
    )
    assert (
        session.interrupted == 0
    ), "safety screen must not interrupt the model when the model wins the grace race"

    # And the screen logged a structured bail so the race is observable.
    bail_lines = [r for r in log.records if r.get("event") == "agent.safety.guard_taken"]
    assert bail_lines, "safety screen must log a structured bail when the guard is taken"


@pytest.mark.asyncio
async def test_grace_window_screen_claims_after_grace_when_model_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the model never calls ``escalate`` during the grace window,
    the safety screen claims the guard once the window expires and
    runs the canned teardown — the floor still fires, just delayed.
    """
    from agent.session import (
        SESSION_END_TOPIC,
        EscalationGuard,
        _wire_model_escalate_teardown,
        _wire_safety_screen,
    )

    monkeypatch.setattr("agent.session._ESCALATION_MODEL_GRACE_SECONDS", 0.05)
    # Skip the post-script audio-drain wait so the test settles quickly.
    monkeypatch.setattr("agent.session._ESCALATION_AUDIO_DRAIN_SECONDS", 0.0)

    persists: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "agent.session.core_safety_events.record",
        lambda *args, **kwargs: persists.append({"args": args, "kwargs": kwargs}),
    )
    delete_calls: list[str] = []

    async def _fake_delete(room_name: str, *, log: Any) -> None:
        delete_calls.append(room_name)

    monkeypatch.setattr("agent.session._delete_room_after_drain", _fake_delete)

    session = _FakeSession()
    # The screen path calls `session.say(script, allow_interruptions=False)`
    # and awaits `SpeechHandle.wait_for_playout()`; replace the file's
    # default async-only `say` with one that matches the production
    # interface so the screen-claims branch is observable.
    spoken: list[str] = []

    class _Handle:
        async def wait_for_playout(self) -> None:
            return None

    def _say(text: str, **_kwargs: Any) -> _Handle:
        spoken.append(text)
        return _Handle()

    session.say = _say  # type: ignore[assignment]
    log = _RecordingLogger()
    deps = _deps()
    room = _RoomFake()
    ctx = _JobCtxFake(room)
    guard = EscalationGuard()
    conv_id = UUID("33333333-3333-3333-3333-333333333333")

    _wire_safety_screen(session, deps, log, conv_id=conv_id, ctx=ctx, guard=guard)
    _wire_model_escalate_teardown(session, deps, log, conv_id=conv_id, ctx=ctx, guard=guard)

    _fire_conversation_item_added(session, _user_item_event("I am having chest pain"))

    # Wait past the grace window with no model tool call.
    await asyncio.sleep(0.15)
    await _drain()

    # Screen ran the full canned teardown — persisted with regex source,
    # spoke the script, emitted the signal, deleted the room.
    assert len(persists) == 1, "screen must persist when the model stays silent"
    assert persists[0]["args"][3] == "regex"
    assert delete_calls == [room.name]
    sent_signals = [s for s in room.sent if s["topic"] == SESSION_END_TOPIC]
    assert len(sent_signals) == 1
    assert spoken, "screen must speak the canned escalation script when it claims after the grace"
