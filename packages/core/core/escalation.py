"""Escalation lifecycle state machine.

Owns the deterministic teardown that fires when a red flag is detected,
on either of the two paths the system supports:

* Server-side regex + classifier hit on a finalised user utterance.
* Realtime model calling the ``escalate`` tool with tier ``emergent``
  or ``urgent``.

Both paths converge on the same shared :class:`EscalationGuard`: the
losing path bails with a structured ``guard_taken`` log line so
teardown is at-most-once per session. Each path has a slightly
different prologue and epilogue:

* The classifier path observes a brief grace window first (so the
  model's tool call wins the race when it's coming on the same turn),
  speaks the canonical script verbatim, sleeps for the audio drain,
  then runs persist → signal → delete.
* The model path claims the guard immediately so the classifier path's
  grace window observes the take and bails. It does *not* re-speak
  the script — the model already produced speech for the same turn —
  but waits for that in-flight speech to finish before persisting,
  signalling, and deleting.

LiveKit-specific operations (TTS playback, data-channel send_text,
server-side room delete) are injected as awaitable callbacks so the
coordinator stays transport-agnostic and unit-testable. The agent
worker (``apps/agent/agent/session.py``) wires those callbacks at
session start.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from core import safety as _safety
from core import safety_events as _safety_events
from core.auth import User

DEFAULT_GRACE_SECONDS = 0.3
"""Grace window between a classifier hit and the guard claim.

Gives the realtime model time to call the ``escalate`` tool itself; if
the model wins the claim during this window the safety screen bails
and the model speaks the routing message with no interrupt and no
overlap. If the model never calls escalate, the screen claims the
guard once the grace expires and runs the canned teardown — so the
safety floor is delayed by at most this long when the model stays
silent.
"""

DEFAULT_AUDIO_DRAIN_SECONDS = 0.5
"""Delay between ``speak_script`` returning and the room teardown.

Tuned to give the realtime model's TTS time to flush its last buffer
before the server-side ``delete_room`` drops the WebRTC connection.
"""


@dataclass(slots=True)
class EscalationGuard:
    """Session-scoped idempotency guard for the two escalation paths.

    A fresh ``EscalationGuard`` is created per agent session so a long-
    running worker does not leak state across sessions; the same
    instance is shared between the classifier-path and model-path
    coordinators so claims race correctly.
    """

    fired: bool = False

    def claim(self) -> bool:
        """Atomically claim the guard.

        Returns ``True`` for the first caller and ``False`` for every
        subsequent caller in the same session.
        """
        if self.fired:
            return False
        self.fired = True
        return True


SpeakScript = Callable[[str, str], Awaitable[None]]
"""``(script, tier) -> awaitable`` — plays the canonical script verbatim."""

EmitSessionEnd = Callable[[str], Awaitable[None]]
"""``(tier) -> awaitable`` — emits the session-end signal to the client."""

DeleteRoom = Callable[[], Awaitable[None]]
"""Tears down the LiveKit room (server-side teardown)."""

WaitForPlayout = Callable[[], Awaitable[None]]
"""Awaits the model's in-flight speech to finish playing."""


@dataclass
class EscalationCoordinator:
    """Per-session escalation state machine.

    Holds the identifying context (user, conv_id, session_id) plus the
    LiveKit-specific adapters. Each path is an async method that runs
    the appropriate prologue, claims the guard, and runs the shared
    tail (log, persist, possibly speak, signal, delete).
    """

    log: Any
    user: User
    session_id: str
    conv_id: UUID | None
    supabase_token: str | None
    guard: EscalationGuard
    speak_script: SpeakScript
    emit_session_end: EmitSessionEnd
    delete_room: DeleteRoom
    grace_seconds: float = DEFAULT_GRACE_SECONDS
    audio_drain_seconds: float = DEFAULT_AUDIO_DRAIN_SECONDS

    async def handle_classifier_result(
        self,
        result: _safety.RedFlagResult,
        utterance: str,
    ) -> None:
        """Path 1 — server-side regex + classifier hit.

        No-op for tiers below ``urgent``. Otherwise: grace window, then
        guard claim, then log, persist, speak the script, drain, signal,
        delete.
        """
        if result.tier not in (_safety.RedFlagTier.EMERGENT, _safety.RedFlagTier.URGENT):
            return

        if self.grace_seconds > 0:
            with contextlib.suppress(Exception):  # sleep should never fail
                await asyncio.sleep(self.grace_seconds)

        if not self.guard.claim():
            self.log.info(
                "agent.safety.guard_taken",
                tier=result.tier.value,
                source=result.source,
            )
            return

        self.log.warning(
            "agent.safety.escalation",
            tier=result.tier.value,
            source=result.source,
            matched_flags=list(result.matched_flags),
            user_id=str(self.user.id),
            session_id=self.session_id,
            conversation_id=str(self.conv_id) if self.conv_id is not None else None,
        )
        self._persist(
            tier=result.tier.value,
            source=result.source,
            matched_flags=list(result.matched_flags),
            utterance=utterance,
        )
        script = _safety.escalation_script_for(result.tier)
        await self.speak_script(script, result.tier.value)
        with contextlib.suppress(Exception):  # sleep should never fail
            await asyncio.sleep(self.audio_drain_seconds)
        await self.emit_session_end(result.tier.value)
        await self.delete_room()

    async def handle_model_escalation(
        self,
        tier: str,
        reason: str,
        wait_for_playout: WaitForPlayout | None,
    ) -> None:
        """Path 2 — realtime model called the ``escalate`` tool.

        No-op for tiers other than ``emergent`` / ``urgent`` (in
        particular ``clinician_soon`` does not tear the session down).
        Claims the guard immediately so the classifier path's grace
        window observes the take and bails. Waits for the model's
        in-flight speech to finish, then persists, signals, and deletes.
        Does not re-speak the script — the model already produced its
        own version of the routing message.
        """
        if tier not in {"emergent", "urgent"}:
            return

        if not self.guard.claim():
            self.log.info(
                "agent.safety.model_escalate.guard_taken",
                tier=tier,
                reason=reason,
            )
            return

        if wait_for_playout is not None:
            try:
                await wait_for_playout()
            except Exception as exc:  # noqa: BLE001 — best-effort wait
                self.log.warning(
                    "agent.safety.model_escalate.wait_failed",
                    tier=tier,
                    error=str(exc),
                )

        self.log.warning(
            "agent.safety.escalation",
            tier=tier,
            source="model",
            matched_flags=[],
            reason=reason,
            user_id=str(self.user.id),
            session_id=self.session_id,
            conversation_id=str(self.conv_id) if self.conv_id is not None else None,
        )
        self._persist(tier=tier, source="model", matched_flags=[], utterance="")
        await self.emit_session_end(tier)
        await self.delete_room()

    def _persist(
        self,
        *,
        tier: str,
        source: str,
        matched_flags: list[str],
        utterance: str,
    ) -> None:
        """Append a row to ``safety_events``. Best-effort.

        A database failure is logged but does not prevent the
        escalation script from playing or the session from ending. The
        safety floor is the script and the session-close; the audit log
        is valuable but not load-bearing.
        """
        if self.conv_id is None:
            self.log.warning("agent.safety.persist_skipped_no_conversation")
            return
        if self.supabase_token is None:
            self.log.warning("agent.safety.persist_skipped_no_token")
            return
        try:
            _safety_events.record(
                self.conv_id,
                self.user.id,
                tier,
                source,
                matched_flags,
                utterance,
                supabase_token=self.supabase_token,
            )
        except Exception as exc:  # noqa: BLE001 — persistence is best-effort
            self.log.warning("agent.safety.persist_failed", error=str(exc))


__all__ = [
    "DEFAULT_AUDIO_DRAIN_SECONDS",
    "DEFAULT_GRACE_SECONDS",
    "DeleteRoom",
    "EmitSessionEnd",
    "EscalationCoordinator",
    "EscalationGuard",
    "SpeakScript",
    "WaitForPlayout",
]
