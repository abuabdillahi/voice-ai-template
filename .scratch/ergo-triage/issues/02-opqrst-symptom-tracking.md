# Issue 02: OPQRST symptom tracking and slot panel

Status: needs-triage

## Parent

`.scratch/ergo-triage/PRD.md`

## What to build

Add structured slot-tracking to the triage interview. After this slice, the agent calls `record_symptom` whenever the user discloses one of the OPQRST slots (location, onset, duration, quality, severity, aggravators, relievers, radiation, prior episodes, occupation context), the slot store accumulates per-session state, and the frontend renders a small live panel that shows what the agent has gathered so far. The panel is the demo legibility lever — it makes the otherwise-invisible interview backbone visible, which proves the model is structuring the conversation rather than free-styling.

The slice introduces `core.triage` as a deep module — a per-session slot store keyed by session id with pure-function setters, a getter, a clear, and a rule-based `differential(state)` that returns a ranked list of `(condition_id, score)` matched against the condition fingerprints from `core.conditions`. The differential ranking is intentionally deterministic and rule-based for the MVP; the seam to swap in a learned ranker later is the function signature itself. The slot store is in-memory only — slots are derivable from the persisted transcript if ever needed offline, and storing them server-side bypasses the `messages` table without buying anything.

A new `core.tools.triage` package exposes `record_symptom(slot, value)` as the single tool registered with the agent in this slice. The agent worker forwards the slot state to the frontend on a new `lk.triage-state` data-channel topic, distinct from the existing `lk.transcription` and `lk.tool-calls` topics, every time a `record_symptom` call commits. The frontend listens on the new topic and renders the slot panel inline alongside the transcript.

## Acceptance criteria

- [ ] `core.triage` module exposes a per-session slot store with `record_symptom(session_id, slot, value)`, `get_state(session_id)`, `clear(session_id)`, and `differential(state) -> list[tuple[str, float]]`. State is held in-process; no database persistence in this slice.
- [ ] Unit tests cover slot set/get/clear, multi-session isolation (two session ids do not bleed), and differential ranking against fixture states (a wrist-numbness state ranks carpal tunnel above lumbar strain; a screen-fatigue state ranks computer vision syndrome above tension-type headache; etc.).
- [ ] `core.tools.triage.record_symptom` is registered with the agent worker. Tool description and parameter schema make the slot vocabulary clear to the realtime model.
- [ ] System prompt is updated to instruct the model to call `record_symptom` whenever the user discloses one of the OPQRST slots, with one call per slot per disclosure.
- [ ] The agent worker emits the current slot state on a new `lk.triage-state` data-channel topic every time a `record_symptom` call commits. The payload shape is documented inline alongside the existing `TOOL_CALLS_TOPIC` constant.
- [ ] The frontend talk page renders a slot panel that subscribes to `lk.triage-state` and displays the gathered slots with their values. Slots not yet disclosed render as a placeholder rather than being hidden.
- [ ] An agent integration test (LiveKit session test harness with a stubbed realtime model) asserts that a scripted user utterance disclosing a slot triggers a `record_symptom` call and that the slot state is observable on the `lk.triage-state` topic.
- [ ] A frontend component test asserts the slot panel renders the expected slots with placeholder values when no state has been received, and updates when a payload arrives.

## Blocked by

`.scratch/ergo-triage/issues/01-triage-pivot-tracer.md`
