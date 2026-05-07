# Issue 02: Model-initiated escalate tool ends the conversation

Status: needs-triage

## What to build

There are two paths today that can recognise a red-flag presentation:

1. **Server-side safety screen** — regex + classifier run on every committed user utterance. Tier-1 (`emergent`) and tier-2 (`urgent`) hits play the scripted escalation message, persist a `safety_events` row, emit the session-end signal on `lk.session-end`, and delete the LiveKit room. The frontend swaps to `EndOfConversationCard`. This path is correct and stays as-is.
2. **Model-callable `escalate` tool** — the realtime model can volunteer an `escalate(tier, reason)` call when it judges escalation is warranted. Today this tool only returns the script string back to the model and the model speaks it; the conversation continues, no audit row is written, and the room stays open.

Close the gap on path 2 so a model-initiated escalation has the same end-of-conversation effect as a safety-screen-initiated one. Trust the model's voice — the model already produces speech for the same turn it issues the tool call, and the system prompt instructs it to mirror the script.

End-to-end behaviour: model calls `escalate(tier='emergent' | 'urgent', reason=...)` → the model finishes speaking its response → the audit row is persisted → the session-end signal is emitted → the LiveKit room is deleted → the frontend renders `EndOfConversationCard` with the appropriate tier copy.

## Acceptance criteria

- [ ] When the realtime model calls `escalate` with tier `emergent` or `urgent`, the agent worker waits for the model's spoken response to that turn to finish playing out, then runs the same teardown sequence the safety screen runs (persist → emit session-end → delete room).
- [ ] When the realtime model calls `escalate` with tier `clinician_soon`, no teardown runs — the conversation continues as it does today, so the user can still ask follow-up questions about scheduling care.
- [ ] The model's spoken reply is not interrupted or re-spoken by the agent worker — we trust the model to read the script from the tool-call result.
- [ ] The model finished-speaking signal is taken from the realtime framework's `speech_created` event and the resulting `SpeechHandle.wait_for_playout()`, not a fixed sleep.
- [ ] The persisted `safety_events` row carries `source="model"`, an empty `matched_flags` array, and an empty `utterance` string. The model-supplied `reason` is captured in structured logs but does not overload `matched_flags`.
- [ ] A session-scoped idempotency guard ensures that if the safety screen and the model's `escalate` tool both fire on the same turn (race), only one teardown runs and only one `safety_events` row is written. The guard is per-session — a long-running worker does not leak state across sessions.
- [ ] If the safety-screen path wins the race, the model-initiated path observes the guard and bails (logs a structured event but does not re-emit the signal, re-persist, or re-attempt deletion).
- [ ] If the model-initiated path wins the race, the safety-screen path observes the guard and bails likewise.
- [ ] No change is required on the frontend: the existing `useSessionEndSignal` hook + tier-aware end-of-conversation card surface the routing copy correctly because the wire payload (`{reason, tier}`) is identical to the safety-screen path.
- [ ] Integration test covers: tier-1 model escalate → teardown runs; tier-2 model escalate → teardown runs; tier-3 model escalate → no teardown; safety-screen-then-model race → single teardown; model-then-safety-screen race → single teardown.

## Blocked by

None - can start immediately.
