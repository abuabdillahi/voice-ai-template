# Issue 04: Safety regex screen and scripted escalate

Status: needs-triage

## Parent

`.scratch/ergo-triage/PRD.md`

## What to build

Land the safety floor. After this slice, every committed user utterance is screened server-side by a deterministic regex/keyword pass against the curated tier-1 phrase list. A match plays the scripted escalation message for the matched tier, ends the session, and emits a structured log line. The screen runs **independently of the realtime model** — it is not a tool the model can choose whether to call. This is the architectural choice that makes the safety layer a floor rather than a behaviour the model could be talked out of.

The slice introduces `core.safety` as a deep module: a `RedFlagTier` enum (`emergent`, `urgent`, `clinician_soon`), a pure `regex_screen(utterance) -> RedFlagResult` function whose phrase list is a single editable constant, the per-tier scripted escalation messages as versioned constants referenced from one place, and a `combine(...) -> RedFlagResult` helper whose precedence rule is "highest tier wins". A new `escalate(tier, reason)` tool is registered with the agent — it is callable by the model when it decides on its own that escalation is warranted, but the parallel regex hook does not depend on the model calling it.

The agent worker gains a `_wire_safety_screen(session, deps, log)` hook on the `conversation_item_added` event. For every committed user utterance, the hook runs the regex screen; if the result is tier-1 or tier-2, the agent worker plays the scripted escalation message via `session.say(...)`, calls the agent worker's session-end path, and emits a structured `agent.safety.escalation` log line carrying the tier, source (`regex` for this slice), matched flags, conversation id, and user id.

Persistence to the `safety_events` table is **not** in scope for this slice — it lands in slice 05. The structured log line is the audit trail for this slice.

## Acceptance criteria

- [ ] `core.safety` module exposes `RedFlagTier` enum with `emergent`, `urgent`, `clinician_soon` members, `regex_screen(utterance) -> RedFlagResult`, `combine(*results) -> RedFlagResult`, and `escalation_script_for(tier) -> str`. The phrase list and the escalation scripts are single editable constants, each with an inline comment naming their authoritative source.
- [ ] The phrase list covers the tier-1 set called out in the PRD: chest pain, sudden severe headache ("worst of my life"), sudden one-sided weakness or numbness, loss of consciousness, sudden vision loss, difficulty breathing. The tier-2 set covers cauda equina markers (bowel or bladder dysfunction with back pain, saddle anaesthesia), progressive neurological deficit, fever with spinal pain, severe trauma history. Each tier-1 and tier-2 phrase has at least one paraphrase in the list.
- [ ] Unit tests cover every tier-1 phrase (each must screen as tier-1), every tier-2 phrase (tier-2), a curated set of false-positive negatives ("my chest feels tight from coughing", "I had a headache last week" — these must not screen as tier-1), and the `combine` precedence rule.
- [ ] `core.tools.triage.escalate(tier, reason)` is registered with the agent worker. The tool plays the scripted message for the tier, marks the session for graceful end, and returns an acknowledgement string.
- [ ] `apps/agent/agent/session.py` includes a `_wire_safety_screen` hook on `conversation_item_added` that runs `core.safety.regex_screen` on every committed user utterance. On tier-1 or tier-2, the hook plays the scripted escalation message via `session.say(...)`, ends the session, and emits an `agent.safety.escalation` structured log line.
- [ ] An agent integration test (LiveKit session test harness with a stubbed realtime model) asserts that a scripted user utterance carrying a tier-1 phrase triggers the safety hook within one turn, the escalation script is played, and the session ends. The test does not depend on the realtime model itself producing the escalation.
- [ ] An agent integration test asserts that a benign utterance ("my wrist tingles a bit") does not trigger the safety hook and the session continues normally.
- [ ] No regression in slot tracking, treatment recommendation, or the slot panel from slices 02 and 03.

## Blocked by

`.scratch/ergo-triage/issues/01-triage-pivot-tracer.md`
