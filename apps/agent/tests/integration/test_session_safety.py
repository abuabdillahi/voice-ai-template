"""Integration-style tests for the safety-screen hook.

The 1.5.x LiveKit Agents test harness for end-to-end voice-loop
scripting is still flagged as an evals tool and brittle across patch
releases (see :mod:`test_session_tools`). Per the established escape
hatch, this test asserts the *contract* the harness would otherwise
verify by driving ``_wire_safety_screen`` against a tiny fake session
and a hand-built ``ConversationItemAddedEvent``.

The fake session captures `say` invocations and exposes an `on(...)`
handler that records the registered listener so the test can fire it
synchronously. This is enough to verify:

* a tier-1 utterance triggers the escalation path within one event,
  including the spoken script and a session close,
* a benign utterance is a noop,
* an assistant role utterance is a noop (the screen only fires on
  user input).
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import pytest
from agent.session import _SessionDeps, _wire_safety_screen
from core import safety
from core.auth import User
from core.config import Settings


@pytest.fixture(autouse=True)
def _silent_classifier(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the gpt-4o-mini classifier to a NONE result by default.

    Slice 06 wires the classifier in parallel with the regex layer.
    Tests that exercise the regex path want the classifier silent so
    they assert on the regex source attribution; tests that target the
    classifier path override this stub with a tier-1 return value.
    """

    async def _stub(_utterance: str, *, settings: Any | None = None) -> safety.RedFlagResult:
        return safety.RedFlagResult(tier=safety.RedFlagTier.NONE, source="classifier")

    monkeypatch.setattr("agent.session.core_safety.classify", _stub)
    # Avoid hitting the global Settings cache and the env-required
    # supabase fields when the agent imports `get_settings()` inside
    # the hook.
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
    """Tiny stand-in for the structlog logger that captures calls.

    The hook calls ``.warning(event, **kwargs)`` and ``.info(event,
    **kwargs)``. Recording each call as a (level, event, kwargs) tuple
    is enough for the assertions below — and avoids the
    ``PrintLogger.msg`` kwarg issue that monkeypatching at the
    structlog processor level introduces.
    """

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


def _deps(log: _RecordingLogger | None = None) -> _SessionDeps:
    logger = log if log is not None else _RecordingLogger()
    return _SessionDeps(
        user=User(id=UUID("11111111-1111-1111-1111-111111111111"), email="alice@example.com"),
        log=logger,
        session_id="user-abc",
    )


class _FakeItem:
    def __init__(self, *, role: str, text: str, item_id: str = "item-1") -> None:
        self.role = role
        self._text = text
        self.id = item_id

    def text_content(self) -> str:
        return self._text


class _FakeEvent:
    def __init__(self, item: _FakeItem) -> None:
        self.item = item


class _FakeSession:
    """Captures listener registration and `say`/`aclose` calls."""

    def __init__(self) -> None:
        self.listeners: dict[str, list[Any]] = {}
        self.said: list[str] = []
        self.closed = False

    def on(self, event: str, handler: Any) -> None:
        self.listeners.setdefault(event, []).append(handler)

    async def say(self, text: str) -> None:
        self.said.append(text)

    async def aclose(self) -> None:
        self.closed = True


def _fire(session: _FakeSession, event: _FakeEvent) -> None:
    """Invoke the registered ``conversation_item_added`` listener."""
    for handler in session.listeners.get("conversation_item_added", []):
        handler(event)


async def _drain() -> None:
    """Yield until any background tasks the listener scheduled finish.

    Slice 06's parallel-screen path uses ``asyncio.gather`` over a
    threaded regex run and an async classifier mock, so the loop has
    to spin enough times for both to resolve plus the chained
    ``say``/``aclose`` awaits.
    """
    for _ in range(50):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_tier1_phrase_triggers_escalation_within_one_turn() -> None:
    session = _FakeSession()
    log = _RecordingLogger()
    deps = _deps(log)

    _wire_safety_screen(session, deps, log)
    _fire(session, _FakeEvent(_FakeItem(role="user", text="I am having chest pain right now")))
    await _drain()

    assert session.said, "the safety hook must speak the escalation script"
    assert session.said[0] == safety.escalation_script_for(safety.RedFlagTier.EMERGENT)
    assert session.closed is True

    escalation_lines = [r for r in log.records if r.get("event") == "agent.safety.escalation"]
    assert escalation_lines, "an agent.safety.escalation log line must be emitted"
    line = escalation_lines[0]
    assert line["tier"] == "emergent"
    assert line["source"] == "regex"
    assert "chest_pain" in line["matched_flags"]
    assert line["session_id"] == "user-abc"


@pytest.mark.asyncio
async def test_benign_user_utterance_is_a_noop() -> None:
    session = _FakeSession()
    log = _RecordingLogger()
    deps = _deps(log)

    _wire_safety_screen(session, deps, log)
    _fire(session, _FakeEvent(_FakeItem(role="user", text="my wrist tingles a bit when I type")))
    await _drain()

    assert session.said == []
    assert session.closed is False
    assert not any(r.get("event") == "agent.safety.escalation" for r in log.records)


@pytest.mark.asyncio
async def test_assistant_role_does_not_trigger_screen() -> None:
    session = _FakeSession()
    log = _RecordingLogger()
    deps = _deps(log)

    _wire_safety_screen(session, deps, log)
    # Even though the *text* would trip the regex, an assistant role
    # must never fire — the safety screen judges user input.
    _fire(
        session,
        _FakeEvent(_FakeItem(role="assistant", text="someone here might say chest pain")),
    )
    await _drain()

    assert session.said == []
    assert session.closed is False


@pytest.mark.asyncio
async def test_safety_hook_does_not_double_fire_for_same_item_id() -> None:
    """If the event ever fires twice for one finalised item, escalation must run at most once."""
    session = _FakeSession()
    log = _RecordingLogger()
    deps = _deps(log)

    _wire_safety_screen(session, deps, log)
    item = _FakeItem(role="user", text="I am having chest pain", item_id="dup-1")
    _fire(session, _FakeEvent(item))
    _fire(session, _FakeEvent(item))
    await _drain()

    assert len(session.said) == 1


@pytest.mark.asyncio
async def test_tier1_phrase_persists_a_safety_event_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Slice 05 — every regex-tier-1 trigger writes one ``safety_events`` row."""
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

    session = _FakeSession()
    log = _RecordingLogger()
    deps = _SessionDeps(
        user=User(id=UUID("11111111-1111-1111-1111-111111111111"), email="alice@example.com"),
        log=log,
        session_id="user-abc",
        supabase_access_token="user-jwt",
    )
    conv_id = UUID("33333333-3333-3333-3333-333333333333")

    _wire_safety_screen(session, deps, log, conv_id=conv_id)
    _fire(session, _FakeEvent(_FakeItem(role="user", text="I am having chest pain right now")))
    await _drain()

    assert len(captured) == 1
    row = captured[0]
    assert row["conversation_id"] == conv_id
    assert row["user_id"] == deps.user.id
    assert row["tier"] == "emergent"
    assert row["source"] == "regex"
    assert "chest_pain" in row["matched_flags"]
    assert row["utterance"] == "I am having chest pain right now"
    assert row["supabase_token"] == "user-jwt"


@pytest.mark.asyncio
async def test_safety_event_persistence_failure_does_not_block_escalation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A database failure must not prevent the escalation script or session-end."""

    def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("postgrest unreachable")

    monkeypatch.setattr("agent.session.core_safety_events.record", _boom)

    session = _FakeSession()
    log = _RecordingLogger()
    deps = _SessionDeps(
        user=User(id=UUID("11111111-1111-1111-1111-111111111111"), email="alice@example.com"),
        log=log,
        session_id="user-abc",
        supabase_access_token="user-jwt",
    )

    _wire_safety_screen(
        session,
        deps,
        log,
        conv_id=UUID("33333333-3333-3333-3333-333333333333"),
    )
    _fire(session, _FakeEvent(_FakeItem(role="user", text="I am having chest pain")))
    await _drain()

    assert session.said, "the escalation script must still play"
    assert session.closed is True
    assert any(r.get("event") == "agent.safety.persist_failed" for r in log.records)


@pytest.mark.asyncio
async def test_safety_event_persistence_skipped_when_no_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[Any] = []

    monkeypatch.setattr(
        "agent.session.core_safety_events.record",
        lambda *a, **k: captured.append((a, k)),
    )

    session = _FakeSession()
    log = _RecordingLogger()
    deps = _SessionDeps(
        user=User(id=UUID("11111111-1111-1111-1111-111111111111"), email="a@b"),
        log=log,
        session_id="user-abc",
        supabase_access_token=None,
    )

    _wire_safety_screen(
        session,
        deps,
        log,
        conv_id=UUID("33333333-3333-3333-3333-333333333333"),
    )
    _fire(session, _FakeEvent(_FakeItem(role="user", text="chest pain")))
    await _drain()

    assert captured == []
    # The escalation still runs even when persistence is skipped.
    assert session.said


@pytest.mark.asyncio
async def test_classifier_only_paraphrase_triggers_escalation_with_classifier_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Slice 06 — a paraphrase the regex misses still escalates via the classifier."""

    async def _classifier_emergent(
        _text: str, *, settings: Any | None = None
    ) -> safety.RedFlagResult:
        return safety.RedFlagResult(
            tier=safety.RedFlagTier.EMERGENT,
            matched_flags=("racing_chest",),
            source="classifier",
        )

    monkeypatch.setattr("agent.session.core_safety.classify", _classifier_emergent)

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
        captured.append({"tier": tier, "source": source, "matched_flags": list(matched_flags)})
        return object()

    monkeypatch.setattr("agent.session.core_safety_events.record", _fake_record)

    session = _FakeSession()
    log = _RecordingLogger()
    deps = _SessionDeps(
        user=User(id=UUID("11111111-1111-1111-1111-111111111111"), email="alice@example.com"),
        log=log,
        session_id="user-abc",
        supabase_access_token="user-jwt",
    )

    _wire_safety_screen(
        session,
        deps,
        log,
        conv_id=UUID("33333333-3333-3333-3333-333333333333"),
    )
    # Phrasing the regex layer does not catch.
    _fire(
        session,
        _FakeEvent(_FakeItem(role="user", text="my heart is racing and my chest feels weird")),
    )
    await _drain()

    assert session.said
    assert session.said[0] == safety.escalation_script_for(safety.RedFlagTier.EMERGENT)
    assert captured
    assert captured[0]["source"] == "classifier"
    assert captured[0]["tier"] == "emergent"


@pytest.mark.asyncio
async def test_both_layers_firing_records_source_both(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _classifier_emergent(
        _text: str, *, settings: Any | None = None
    ) -> safety.RedFlagResult:
        return safety.RedFlagResult(
            tier=safety.RedFlagTier.EMERGENT,
            matched_flags=("classifier_paraphrase",),
            source="classifier",
        )

    monkeypatch.setattr("agent.session.core_safety.classify", _classifier_emergent)

    captured: list[dict[str, Any]] = []

    monkeypatch.setattr(
        "agent.session.core_safety_events.record",
        lambda *a, **k: captured.append({"args": a, "kwargs": k}),
    )

    session = _FakeSession()
    log = _RecordingLogger()
    deps = _SessionDeps(
        user=User(id=UUID("11111111-1111-1111-1111-111111111111"), email="a@b"),
        log=log,
        session_id="user-abc",
        supabase_access_token="user-jwt",
    )

    _wire_safety_screen(
        session,
        deps,
        log,
        conv_id=UUID("33333333-3333-3333-3333-333333333333"),
    )
    # Tier-1 phrase that the regex layer also catches.
    _fire(session, _FakeEvent(_FakeItem(role="user", text="I am having chest pain right now")))
    await _drain()

    assert captured
    args = captured[0]["args"]
    # Positional record(conv_id, user_id, tier, source, matched_flags, utterance)
    assert args[3] == "both"
    # And the union of flags from both layers is recorded.
    assert "chest_pain" in args[4]
    assert "classifier_paraphrase" in args[4]


@pytest.mark.asyncio
async def test_classifier_failure_falls_back_to_regex_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A classifier crash must not prevent the regex floor from firing."""

    async def _classifier_boom(_text: str, *, settings: Any | None = None) -> safety.RedFlagResult:
        raise RuntimeError("transient openai outage")

    monkeypatch.setattr("agent.session.core_safety.classify", _classifier_boom)
    monkeypatch.setattr(
        "agent.session.core_safety_events.record",
        lambda *a, **k: None,
    )

    session = _FakeSession()
    log = _RecordingLogger()
    deps = _SessionDeps(
        user=User(id=UUID("11111111-1111-1111-1111-111111111111"), email="a@b"),
        log=log,
        session_id="user-abc",
        supabase_access_token="user-jwt",
    )

    _wire_safety_screen(
        session,
        deps,
        log,
        conv_id=UUID("33333333-3333-3333-3333-333333333333"),
    )
    _fire(session, _FakeEvent(_FakeItem(role="user", text="I am having chest pain")))
    await _drain()

    assert session.said
    # The regex floor still fires — escalation is not gated on the classifier.
    assert session.said[0] == safety.escalation_script_for(safety.RedFlagTier.EMERGENT)


class _RealtimeFakeSession:
    """Fake session that mimics realtime mode with a TTS attached.

    With a TTS attached at AgentSession construction (see
    :func:`core.realtime.create_safety_tts`), ``session.say(text)``
    works in realtime mode and plays the script verbatim. But the
    realtime model has typically already started its own auto-reply
    by the time the safety screen fires, so the hook must call
    ``interrupt()`` before ``say()`` — otherwise the script audio
    overlaps the model's reply.

    This fake records call order and asserts that contract.
    """

    def __init__(self) -> None:
        self.listeners: dict[str, list[Any]] = {}
        self.said: list[str] = []
        self.calls: list[str] = []
        self.closed = False

    def on(self, event: str, handler: Any) -> None:
        self.listeners.setdefault(event, []).append(handler)

    async def interrupt(self) -> None:
        self.calls.append("interrupt")

    async def say(self, text: str) -> None:
        self.calls.append("say")
        self.said.append(text)

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_realtime_escalation_interrupts_then_says_script(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In realtime mode, interrupt the in-flight reply before speaking the script.

    Regression: an earlier implementation tried to fall back to
    ``generate_reply(instructions=script)``, which raced with the
    model's auto-reply ("conversation_already_has_active_response"),
    let the model paraphrase, and clipped the audio at session close.
    The fix attaches a TTS so ``say()`` works in realtime mode, and
    the hook ``interrupt()``-s any in-flight response first.
    """
    monkeypatch.setattr(
        "agent.session.core_safety_events.record",
        lambda *a, **k: None,
    )

    session = _RealtimeFakeSession()
    log = _RecordingLogger()
    deps = _SessionDeps(
        user=User(id=UUID("11111111-1111-1111-1111-111111111111"), email="a@b"),
        log=log,
        session_id="user-abc",
        supabase_access_token="user-jwt",
    )

    _wire_safety_screen(
        session,
        deps,
        log,
        conv_id=UUID("33333333-3333-3333-3333-333333333333"),
    )
    _fire(session, _FakeEvent(_FakeItem(role="user", text="I am having chest pain")))
    await _drain()

    assert session.calls[:2] == [
        "interrupt",
        "say",
    ], f"interrupt must be awaited before say; got {session.calls}"
    assert session.said == [safety.escalation_script_for(safety.RedFlagTier.EMERGENT)]
    assert session.closed is True
    # An info log line marks where in the timeline the TTS speak
    # occurs — the per-utterance TTS metrics line lives on a different
    # logger so it's hard to correlate without an explicit anchor.
    spoken = [r for r in log.records if r.get("event") == "agent.safety.script_spoken"]
    assert spoken, "an agent.safety.script_spoken info log must mark when say() ran"
    assert spoken[0]["tier"] == "emergent"


@pytest.mark.asyncio
async def test_tier2_phrase_also_triggers_escalation() -> None:
    session = _FakeSession()
    log = _RecordingLogger()
    deps = _deps(log)

    _wire_safety_screen(session, deps, log)
    _fire(
        session,
        _FakeEvent(_FakeItem(role="user", text="I am numb between my legs and my back hurts")),
    )
    await _drain()

    assert session.said
    assert session.said[0] == safety.escalation_script_for(safety.RedFlagTier.URGENT)
    escalation_lines = [r for r in log.records if r.get("event") == "agent.safety.escalation"]
    assert escalation_lines[0]["tier"] == "urgent"
