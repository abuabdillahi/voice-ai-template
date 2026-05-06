# Issue 02: Inject prior-session recall into the triage system prompt

Status: ready-for-agent

## Parent

`.scratch/ergo-triage-recall/PRD.md`

## What to build

At the start of each new triage session, fetch the user's last three condition-bearing prior conversations and inject them as a structured block at the top of the system prompt. The agent's opener becomes proactive when there is a recent identified-condition session: it acknowledges the condition by name, offers a fork between following up on the previous condition and raising something new, and is forbidden from quoting any treatment specifics from the recall blob — new specifics this session must come fresh from `recommend_treatment` like always.

Users with no prior condition-bearing sessions (first-time users, or returning users whose prior sessions all ended without an identified condition) see a system prompt byte-for-byte identical to today's static `SYSTEM_PROMPT`. This is the regression-test anchor.

The deep module introduced in this slice is `build_triage_system_prompt(prior_sessions: list[PriorSession]) -> str` — a pure function over a fixed-shape input that produces the rendered prompt. The existing module-level `SYSTEM_PROMPT` constant in `apps/agent/agent/session.py` is retired (or computed lazily as `build_triage_system_prompt([])` for back-compat with any tests importing it); the entrypoint computes the prompt per-session after fetching prior conversations.

The fetch is a new function `core.conversations.list_recent_with_recall(user, *, limit=3, supabase_token)` returning a new dataclass `PriorSession(started_at, identified_condition_id, recall_context)`. It lives separately from the existing `list_for_user` so the `/conversations` API endpoint contract — which serves `ConversationSummary` — is unchanged.

The disposition note at `apps/agent/agent/session.py:23-31` is updated to acknowledge that a third memory surface — prompt-time injection of structured triage-outcome facts — has been added on top of the existing decisions to bypass mem0 and the personalisation `build_system_prompt`. The note records the safety constraints that make this surface acceptable where the others were not (condition-named only, numbers-forbidden, last-three-condition-filtered, no model decision required).

## Acceptance criteria

- [ ] New dataclass `core.conversations.PriorSession` with fields `started_at: datetime`, `identified_condition_id: str`, `recall_context: str | None`. Frozen, slotted, exported in `__all__`.
- [ ] New function `core.conversations.list_recent_with_recall(user, *, limit: int = 3, supabase_token: str) -> list[PriorSession]`. Filters to `identified_condition_id IS NOT NULL`, orders `started_at DESC`, applies `limit`. Raises `PermissionError` on missing token (consistent with the other token-scoped functions in the module). The existing `list_for_user` and `ConversationSummary` are not modified.
- [ ] New helper `apps/agent/agent/session.py::build_triage_system_prompt(prior_sessions: list[PriorSession]) -> str`. With `prior_sessions == []`, the rendered string is byte-for-byte identical to today's static `SYSTEM_PROMPT`. With a non-empty list, the prompt is prepended with a two-part block: first a "Most recent session" sub-block naming the most recent prior session's identified condition and recall context (drives the opener), then an "Earlier sessions (for pattern recognition, do not open by referencing these)" sub-block listing the remaining sessions.
- [ ] The prompt language adds two new rules verbatim: (a) when a "Most recent session" block is present, open by naming the condition and offering the fork between following up on that and raising something new; (b) never quote treatment specifics, stretch durations, exercise rep counts, contraindications, or expected timelines from the recall block — new specifics this session must come fresh from `recommend_treatment`.
- [ ] The module-level `SYSTEM_PROMPT` constant in `apps/agent/agent/session.py` is retired. If any existing imports of `SYSTEM_PROMPT` would break, either update the import sites or expose `SYSTEM_PROMPT = build_triage_system_prompt([])` as a lazy alias for back-compat — pick whichever is smaller in this codebase at implementation time.
- [ ] The agent worker's `entrypoint` fetches prior sessions via `list_recent_with_recall` after resolving `supabase_token`, before constructing the agent. The fetch is best-effort: a raised exception, a missing token, or an empty list all degrade to `build_triage_system_prompt([])` and the user gets a default opener identical to today's. Failures are logged at `warning` level with a structured event name so they are observable in production.
- [ ] The disposition note at `apps/agent/agent/session.py:23-31` is updated to describe the new prompt-injection memory surface and its safety constraints (condition-named, numbers-forbidden, last-three-condition-filtered, no model decision required), and to clarify that this is *additional to* — not a reversal of — the existing decisions to keep mem0 and the personalisation `build_system_prompt` bypassed for triage.
- [ ] Unit tests for `build_triage_system_prompt`: empty input matches today's static prompt (assert via the retained `SYSTEM_PROMPT` alias or a stored snapshot); a single `PriorSession` produces a prompt containing the literal `identified_condition_id` and the literal `recall_context`; a three-element input produces both the "Most recent session" block and the "Earlier sessions" block listing the remaining two; the two new prompt rules appear verbatim in the rendered prompt.
- [ ] Integration assertion in the agent test harness: with a stubbed `list_recent_with_recall` returning one fixture `PriorSession`, a session-start dry-run produces an `Agent` whose `instructions` string contains the fixture's `identified_condition_id`. With the fetcher returning `[]`, the rendered instructions are byte-for-byte identical to today's `SYSTEM_PROMPT`.
- [ ] No new tool registration for the triage product. `remember`/`recall` stay unregistered, exactly as today. The episodic-memory tool surface is unchanged.

## Blocked by

`.scratch/ergo-triage-recall/issues/01-capture-identified-condition-and-recall-context.md`

## Comments

> *This was generated by AI during triage.*

### Agent Brief

**Category:** enhancement

**Summary:** At triage session start, fetch the user's last three condition-bearing prior sessions and inject them as a structured block at the top of the system prompt; opener becomes proactive (names the condition, never the numbers) when a recent identified-condition session exists.

The "What to build" narrative and "Acceptance criteria" sections above already cover current/desired behaviour, the deep-module interface (`build_triage_system_prompt(prior_sessions)`), the new fetcher and dataclass shape, the empty-input invariance regression anchor, and concrete testable criteria including verbatim presence of the two new prompt rules. Treat those as the contract.

**Out of scope** (see PRD `.scratch/ergo-triage-recall/PRD.md` for the full list): no `remember`/`recall` tool re-registration, no extension of `build_system_prompt(preferred_name, preferences)` (sibling helper, not a signature widen), no changes to `ConversationSummary` or the `/conversations` API contract, no soft opener for null-condition recent sessions, no configurable cardinality, no UI surfacing of recall context.
