# Issue 05: `lk.session-end` topic and tier-aware end-of-call card on escalation

Status: ready-for-agent

## Parent

`.scratch/sarjy-product-polish/PRD.md`

## What to build

When the safety screen fires a tier-1 (`emergent`) or tier-2 (`urgent`) escalation, the user gets visible UI feedback that the call has ended *and* tier-appropriate routing copy in writing — not just the existing scripted spoken message and a UI that still reads "Connected".

End-to-end vertical:

- Agent emits a structured `{reason: "escalation", tier: "emergent" | "urgent"}` payload on a new `lk.session-end` data-channel topic before speaking the escalation script.
- Agent waits for the script audio to drain (~500 ms; tune if escalation tests show clipping) before tearing the room down.
- Agent replaces the existing `session.aclose()` / `session.close()` call with a server-side LiveKit room delete, so a misbehaving frontend cannot leave the room open.
- Frontend exposes a new `useSessionEndSignal(room)` hook that subscribes to `lk.session-end`, parses the payload, and returns the latest signal.
- A new `EndOfCallCard` component renders tier-aware copy (tier-1 → "Call your local emergency number now."; tier-2 → "Please seek urgent care today.") with no Reconnect button.
- `talk-page.tsx` consumes the hook; on a non-null signal it replaces the transcript area with the end-of-call card and triggers `room.disconnect()` after a short delay matching the server-side audio-drain window.

The new topic name `lk.session-end` is added as a module-level constant in `agent.session` alongside `TOOL_CALLS_TOPIC` and `TRIAGE_STATE_TOPIC`. The payload `reason` field is open for future expansion (e.g. `"out_of_scope"`) but only `"escalation"` is emitted in this issue's scope.

The existing `_persist_safety_event` and `_wire_end_conversation_on_shutdown` paths are preserved unchanged — both run on the room close that the new teardown produces, so safety-event persistence and conversation-end summary generation continue to work.

Test-first (TDD): write the failing tests for `useSessionEndSignal` (the five cases from the PRD) before the implementation. Extend the existing safety-screen integration test under `apps/agent/tests/` to assert the new topic emission and the room-delete fallback path.

## Acceptance criteria

- [ ] `agent.session.SESSION_END_TOPIC` is defined as a module-level constant equal to `"lk.session-end"`, alongside `TOOL_CALLS_TOPIC` and `TRIAGE_STATE_TOPIC`.
- [ ] `_wire_safety_screen` emits the `{reason, tier}` payload on `SESSION_END_TOPIC` *before* `_speak_escalation_script` is called.
- [ ] After the escalation script returns, the safety flow waits a brief audio-drain delay before tearing down, then performs a server-side LiveKit room delete instead of `session.aclose()` / `session.close()`.
- [ ] `_persist_safety_event` and `_wire_end_conversation_on_shutdown` continue to fire correctly on the new teardown path — safety event persistence and conversation `end()` still run.
- [ ] An `agent.safety.session_end_signal_emitted` structured log line is emitted when the topic payload is sent, with `tier` and `reason` fields.
- [ ] `apps/web/src/lib/livekit-session-end.ts` exports `useSessionEndSignal(room: Room | null)` returning `{reason, tier} | null`.
- [ ] Unit tests cover the five `useSessionEndSignal` cases from the PRD (null before any event, parsed payload after a well-formed event, ignores other topics, returns null on malformed JSON, cleans up subscription on unmount), written before the implementation.
- [ ] `apps/web/src/components/end-of-call-card.tsx` exists and renders tier-aware copy with no Reconnect button.
- [ ] `talk-page.tsx` consumes `useSessionEndSignal`, replaces the transcript area with the end-of-call card on a non-null signal, and triggers `room.disconnect()` after the audio-drain delay.
- [ ] The existing safety-screen integration test under `apps/agent/tests/` is extended to assert the new topic emission and the server-side room-delete fallback fires when the frontend is not present to disconnect.
- [ ] No changes to `core.safety` regex patterns, the classifier, or the escalation script wording — the escalation flow is rewired, the escalation content is not.
- [ ] No Reconnect / "Try again" affordance anywhere on the end-of-call card or in the talk-page state machine when the end-card is showing.
- [ ] Web app builds, type-checks, and the existing test suite passes; agent test suite passes.

## Blocked by

None - can start immediately.
