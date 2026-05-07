# Issue 03: English-only language constraint in the system prompt

Status: ready-for-agent

## Parent

`.scratch/sarjy-product-polish/PRD.md`

## What to build

A single declarative system-prompt rule that constrains the agent to English-only replies and prescribes a stable refusal pattern when the user speaks another language. On the first non-English user utterance the agent says, in English, "I can only respond in English — could you repeat that in English?". On a second non-English utterance the agent re-states the constraint and stops progressing the OPQRST interview. The agent never silently translates a non-English utterance into an English reply.

The rule is added to the static-prompt section of `build_triage_system_prompt` so it applies in every render — first-time, returning, with-priors, without-priors. There is no transcription-side change: the live `lk.transcription` topic continues to receive the user's words in whatever language they spoke them.

Test-first (TDD): write the failing prompt-render assertions for the new rule appearing verbatim in every branch before adding the rule to the prompt builder.

## Acceptance criteria

- [ ] A single new declarative rule is added to the static section of `build_triage_system_prompt` covering the English-only behaviour and the once-then-stable-refusal pattern, with the verbatim phrasing from the PRD's "English-only rule" implementation decision.
- [ ] Unit tests assert the new rule appears verbatim in the rendered prompt for every existing branch — `(is_returning_user=False, prior_sessions=[])`, `(is_returning_user=True, prior_sessions=[])`, and `(is_returning_user=True, prior_sessions=[PriorSession])` — written before the rule is added to the builder.
- [ ] The first-time-no-priors regression assertion is updated once, deliberately, to include the new rule — and remains the new byte-for-byte reference for first-time users going forward.
- [ ] No transcription-side `language=en` constraint is introduced on the realtime model or any STT layer.
- [ ] No changes to `core.safety` regex patterns, the safety classifier, or the `core.realtime` factory.
- [ ] Existing prompt regression tests for the recall feature's prior-session block and the "name the condition, never the numbers" rule continue to pass unchanged.
- [ ] Agent test suite passes.

## Blocked by

- `.scratch/sarjy-product-polish/issues/01-sarjy-rebrand-and-first-time-intro.md`
