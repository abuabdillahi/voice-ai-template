# Issue 06: Safety classifier (gpt-4o-mini)

Status: needs-triage

## Parent

`.scratch/ergo-triage/PRD.md`

## What to build

Add the second layer of the defence-in-depth red-flag detector. After this slice, every committed user utterance is screened by both the deterministic regex layer (slice 04) and a parallel `gpt-4o-mini` classifier; the higher tier wins via `core.safety.combine`. The classifier catches paraphrased and ambiguous presentations the regex layer cannot — "my heart is racing and my chest feels weird" does not trip the regex phrase list but is a tier-1 presentation a clinician would want flagged. Reusing the existing `OPENAI_API_KEY` keeps the credential surface unchanged.

The slice adds `core.safety.classify(utterance) -> RedFlagResult` as an async function that calls the OpenAI Chat Completions API with a `response_format={"type": "json_schema", ...}` argument so the classifier returns `{tier, matched_flags}` deterministically. The classifier prompt is a single versioned constant in the module that names the three tiers, lists representative phrases for each, and instructs the classifier to return `none` when no red flag is present. The classifier model id is read from a new optional setting `SAFETY_CLASSIFIER_MODEL` defaulting to `gpt-4o-mini`.

The safety hook in the agent worker is amended to fire the regex screen and the classifier in parallel via `asyncio.gather`. The combined result drives escalation — if either layer fires tier-1 or tier-2, the agent escalates. The persisted `safety_events` row's `source` column reflects which layer (or both) caught the trigger.

## Acceptance criteria

- [ ] `core.safety.classify(utterance, *, settings) -> RedFlagResult` is implemented as an async function that calls the OpenAI Chat Completions API with structured output requesting `{tier: "emergent"|"urgent"|"clinician_soon"|"none", matched_flags: list[str]}`. Failure modes (timeout, API error, malformed response) return a `none`-tier result with a logged warning rather than raising.
- [ ] The classifier system prompt is a versioned constant named `CLASSIFIER_SYSTEM_PROMPT` in the module. It names the three tiers, lists representative phrases for each, and instructs the classifier to return `none` when no red flag is present.
- [ ] `Settings` in `core.config` is extended with `safety_classifier_model: str` defaulting to `"gpt-4o-mini"`. The classifier reads the model id from the typed settings rather than a literal.
- [ ] Unit tests cover the classifier with the OpenAI client mocked at the transport boundary: each of the three non-`none` tiers returns the expected shape; an OpenAI timeout returns `none` and emits the expected warning log; a malformed JSON response returns `none` with a logged warning.
- [ ] `core.safety.combine(regex_result, classifier_result) -> RedFlagResult` returns the higher tier and unions the matched flags. The `source` field is `regex` if only the regex layer fired, `classifier` if only the classifier fired, `both` if both fired the same or different non-`none` tiers.
- [ ] The safety hook in `apps/agent/agent/session.py` runs the regex screen and the classifier in parallel via `asyncio.gather` on every committed user utterance. The combined result drives escalation.
- [ ] The persisted `safety_events` row from slice 05 records the `source` field correctly for classifier-only and combined triggers.
- [ ] An agent integration test asserts that a paraphrased tier-1 utterance the regex layer does not catch ("my heart is racing and my chest feels weird") triggers escalation via the classifier source and produces a `safety_events` row with `source = "classifier"`.
- [ ] An agent integration test asserts that an utterance both layers catch produces a `safety_events` row with `source = "both"`.
- [ ] No regression in slice 04's regex-only path: tier-1 phrases that the regex layer catches still escalate (and are now recorded with `source = "both"` if the classifier also catches them, or `source = "regex"` if only the regex layer does).

## Blocked by

`.scratch/ergo-triage/issues/05-safety-events-audit-log.md`
