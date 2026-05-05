# Issue 03: Grounded treatment recommendation

Status: needs-triage

## Parent

`.scratch/ergo-triage/PRD.md`

## What to build

Close the triage loop by giving the agent a grounded path to a treatment recommendation. After this slice, once the slot store is populated enough to support a confident differential, the agent picks a top condition, calls `recommend_treatment(condition_id)`, and reads back the conservative protocol verbatim from the condition record. The model is forbidden — by system prompt — from speaking any protocol, stretch duration, exercise rep count, or treatment timeline that did not come from this tool. This is the structural antidote to the dosage-hallucination failure mode the PDF flags as the worst-case medical-adjacent risk.

The slice adds `recommend_treatment(condition_id)` to `core.tools.triage`, which validates the `condition_id` against `core.conditions.CONDITIONS` and returns the protocol block (conservative treatment, contraindications, expected recovery timeline, condition-specific monitoring guidance). It also exposes the differential ranking from `core.triage` to the model so the model has a principled basis for picking a `condition_id`. The system prompt is amended to require a confidence threshold — if the top-ranked condition's score is below the threshold, the model recommends professional evaluation instead of speaking a treatment protocol.

The slice does not touch the safety layer; tier-1/2 escalation remains independent and is delivered in slice 04.

## Acceptance criteria

- [ ] `core.tools.triage.recommend_treatment(condition_id)` is registered with the agent worker. The tool validates `condition_id` against `core.conditions.CONDITIONS` and returns a structured payload (conservative treatment, contraindications, expected timeline, condition-specific monitoring guidance, source citations). Unknown `condition_id` returns a clean error string the model can verbalise rather than raising.
- [ ] `core.triage.differential(state)` is callable from the agent worker and its top-N output is exposed to the model — either via a `get_differential()` tool or by including the current ranked list in the system prompt at session start (the slice may pick whichever is cleaner; document the choice inline).
- [ ] The system prompt is amended with the rule "never speak a protocol, stretch duration, exercise rep count, or numerical timeline that did not come from `recommend_treatment`" and a confidence-threshold rule "if the top-ranked condition's score is below the documented threshold, recommend professional evaluation rather than calling `recommend_treatment`".
- [ ] Unit tests cover `recommend_treatment` happy path (each of the five conditions returns the expected protocol shape), invalid `condition_id` (returns the error string), and the validation that no protocol field is empty.
- [ ] An agent integration test asserts that a scripted slot-disclosure sequence ending in a high-confidence carpal-tunnel-shaped state triggers a `recommend_treatment("carpal_tunnel")` call and that the model verbalises content from the returned protocol.
- [ ] An agent integration test asserts that a scripted ambiguous state (low top-score) does not trigger `recommend_treatment` and the model recommends professional evaluation instead.
- [ ] No regression in slice 02's slot-tracking behaviour or the slot panel.

## Blocked by

`.scratch/ergo-triage/issues/02-opqrst-symptom-tracking.md`
