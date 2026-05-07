# Issue 02: Branch the disclaimer for returning users via `has_prior_session`

Status: ready-for-agent

## Parent

`.scratch/sarjy-product-polish/PRD.md`

## What to build

A returning user — defined as any user with at least one prior conversation row — hears a short refresher (`"Hi, Sarjy here. Quick reminder I'm still an educational tool, not a doctor."`) instead of the full disclaimer. The signal is broader than "had a condition-bearing prior session" by design: a user who connected once and dropped before reaching a condition has still heard the disclaimer and should be treated as returning.

End-to-end vertical: a new narrowly-scoped Supabase query (`core.conversations.has_prior_session`), a new keyword argument on `build_triage_system_prompt` (`is_returning_user: bool = False`), the entrypoint wiring that calls the query at session start and threads the flag through, the prompt branch that selects the short refresher instead of the full disclaimer, and a structured log line marking when the short branch is taken.

When the prior-session block from the existing recall feature is also present (returning user *with* a condition-bearing prior session), the short refresher composes with that block — short refresher first, then the existing prior-condition fork.

Test-first (TDD): write the failing tests for `has_prior_session` and the three new branches of `build_triage_system_prompt` before the implementation.

## Acceptance criteria

- [ ] `core.conversations.has_prior_session(user, *, supabase_token) -> bool` exists, returns `True` for users with ≥ 1 prior conversation row and `False` otherwise; raises become `False` with a structured warning log.
- [ ] Unit tests cover the four `has_prior_session` cases from the PRD's testing decisions (count ≥ 1, count 0, raised exception, token-scoped client invocation), written before the implementation lands.
- [ ] `build_triage_system_prompt` accepts `is_returning_user: bool = False` as a keyword argument.
- [ ] Unit tests cover the three branches `(False, [])`, `(True, [])`, `(True, [PriorSession])` plus the regression that the new English-only rule (issue 03) and the existing "name the condition, never the numbers" rule are present in every relevant branch — these tests are written first and fail before the implementation.
- [ ] The `(False, [])` rendering remains the agent's regression anchor for first-time users (and is updated only as required by issues 01 and 03; this issue must not modify it further).
- [ ] The `(True, [])` rendering contains the literal `"Hi, Sarjy here. Quick reminder I'm still an educational tool, not a doctor."` opener and does not contain the full-disclaimer instruction.
- [ ] The `(True, [PriorSession])` rendering composes the short refresher with the existing "Most recent session" prior-condition block.
- [ ] The agent entrypoint calls `has_prior_session` alongside the existing `list_recent_with_recall` call and passes the result into `build_triage_system_prompt(... , is_returning_user=...)`.
- [ ] A best-effort failure path on `has_prior_session` (transient Supabase error) defaults to `is_returning_user=False`, plays the full disclaimer, and emits a structured warning log.
- [ ] An `agent.disclaimer.short_branch` structured log line is emitted at session start when the short branch is selected.
- [ ] The integration assertion in the agent test harness covers a stubbed `has_prior_session=True` end-to-end through to the rendered `Agent.instructions` containing the short-refresher phrasing.

## Blocked by

- `.scratch/sarjy-product-polish/issues/01-sarjy-rebrand-and-first-time-intro.md`
