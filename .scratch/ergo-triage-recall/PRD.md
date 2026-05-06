# PRD: Prior-session recall for the ergo triage agent

**Type:** feature on the existing ergo-triage product
**Status:** needs-triage
**State:** unscoped — implementation issues to be split out under `.scratch/ergo-triage-recall/issues/` after triage

## Problem Statement

A returning user starts every triage session from a blank slate. The agent has no idea whether they spoke to it last week about wrist tingling, what condition was identified, what conservative-treatment protocol they were given, or whether the recommended exercises helped. Every session re-runs the OPQRST interview from zero. From the user's perspective the product feels amnesiac: they expect a tool that "remembers we talked about the carpal tunnel last time — has it gotten better?" and instead get an opener that asks again where the discomfort is located.

The cost is twofold. First, the user wastes time re-disclosing context the agent could already have. Second — and more importantly for a product whose value is the *follow-up* loop — outcomes are never captured. Without the agent asking "did the median nerve glides help?" at the start of the next session, there is no signal at all about whether the conservative-treatment protocol worked, persisted, or got worse. The clinical pattern that matters most ("this is the third visit for the same wrist symptoms") cannot be surfaced because the agent never sees the prior visits.

The mem0-backed episodic memory the template ships with is deliberately not registered for the triage product (per the disposition note in the agent worker): mem0 is for *consciously remembered* facts the model chose to write, and exposing it as a free-form recall surface in a medical-adjacent product reintroduces the hallucination risk the system prompt's hard rules are built to avoid. The need here is different — it is about every prior session being recallable as structured-enough context to drive a safe follow-up opener, not about the model deciding when to write or read a memory.

## Solution

When a triage session ends, generate a richer `recall_context` blob alongside the existing one-sentence `summary`, and persist the identified condition deterministically as its own column on the conversation. When the same user starts a new session, fetch their last three sessions where a condition was identified and inject that context directly into the system prompt — no new tool surface, no model decision about when to recall.

The opener becomes proactive: if a recent session identified a condition, the agent's first turn (after the standard scope/disclaimer) names that condition and offers a fork — *"Are you checking back on that, or is something new bothering you?"* — and the user's answer becomes the next session's outcome record, captured organically in the transcript. The opener is allowed to name the *condition* but never the numerical specifics of the protocol that was given. New treatment specifics in this session must come fresh from `recommend_treatment` like always.

Older sessions in the prompt block (positions two and three) are surfaced for pattern recognition only — the model is explicitly instructed not to open by referencing them — so a recurring pattern ("third visit for the same wrist symptoms") becomes available to the agent's reasoning without producing a creepy "I see you've been here three times" opener.

The history-list UI is left alone: `summary` keeps its one-sentence shape and renders unchanged. `recall_context` is a separate column read only by the agent at session-start time.

The feature is forward-only — no backfill of existing conversations. Each user's recall lights up on the second session they end after this ships.

## User Stories

### End user — returning visitor with a prior identified condition

1. As a returning office worker who was identified with upper trapezius strain last week, I want the agent to acknowledge that prior visit in its opening turn, so that I do not have to re-explain who I am or why I called before.
2. As a returning office worker, I want the agent to ask whether I am following up on the previous condition or have something new, so that I can redirect the conversation without having to interrupt a re-run of the OPQRST interview.
3. As a returning office worker following up on a prior recommendation, I want to be able to say "yes, I tried the stretches and the pain is better", so that my outcome is captured for next time without me having to fill out a form.
4. As a returning office worker following up on a prior recommendation, I want to be able to say "the stretches did not help", so that the agent can take that into account before suggesting the same protocol again.
5. As a returning office worker who is not following up — I have a brand-new headache this time — I want the agent to drop the prior topic immediately when I say so, so that I am not railroaded into discussing my wrist when my head hurts.

### End user — recurring pattern recognition

6. As an office worker whose carpal tunnel symptoms have come back for the third time, I want the agent to be aware of the pattern even if it does not open by saying so, so that the recommendation in this session can reflect that this is recurring rather than first-presentation.
7. As an office worker, I do not want the agent to greet me with a wall-of-text recap of every session I have had, so that the conversation feels natural and not surveillance-y.

### End user — first-time visitor and edge cases

8. As a first-time office worker with no prior sessions, I want the agent to open exactly as it does today (scope/disclaimer + first OPQRST question), so that the new feature does not change the experience for users it does not apply to.
9. As an office worker whose only prior session ended without identifying a condition (out-of-scope, immediate escalation, very short), I want the agent to open normally rather than awkwardly trying to follow up on a session that produced no actionable result, so that the opener does not feel disjointed.
10. As an office worker whose prior session ended a long time ago, I want the agent to still recognise the prior identified condition rather than silently discarding it, so that "checking back on that wrist thing from a few months ago" still works.

### End user — safety and trust

11. As a returning office worker, I do not want the agent to quote a specific stretch duration, exercise rep count, or expected timeline back to me from memory, so that the agent's safety contract — never speak treatment numbers from its own knowledge — is preserved across sessions, not just within one.
12. As a returning office worker, I want any new treatment specifics in this session to come from a fresh `recommend_treatment` call rather than recycled from the prior session's recall blob, so that I am not reading content that may have changed in the knowledge base.
13. As a returning office worker, I want the agent's cross-session memory to be scoped to my account, so that another user's prior sessions cannot leak into my prompt.

### End user — outcome capture

14. As an office worker reporting back on a prior recommendation, I want my "yes it helped" / "no it did not" answer to be captured as part of the next session's recall, so that the third session can see the second session's outcome.
15. As an office worker who never followed up on a prior recommendation because I forgot, I want the agent's question to remind me that I had a recommendation to try, so that I am nudged to actually engage with the conservative-treatment protocol rather than ignoring it.

### Maintainer — auditability and safety floor

16. As a maintainer, I want the identified condition for each conversation to be derivable deterministically from the persisted `tool` messages rather than extracted by an LLM, so that the field used to drive the next session's opener is auditable and not subject to hallucination.
17. As a maintainer, I want the existing one-sentence `summary` field to keep its shape, so that the history-list UI does not regress and the existing API contract for `/conversations` does not change.
18. As a maintainer, I want the rendered system prompt for a user with no prior sessions to be byte-for-byte identical to today's static system prompt, so that the change has a clean regression-test anchor and behaviour is unchanged for first-time users.
19. As a maintainer, I want the prior-session block in the prompt to be bounded (last three, condition-filtered), so that prompt size and per-session token cost do not grow unboundedly with a returning user's history.
20. As a maintainer, I want the failure mode for the recall-context generation step to fall back gracefully (populate `summary` with the truncation fallback, leave `recall_context` NULL), so that a transient OpenAI failure at session-end does not break the session-end path or block the next session.
21. As a maintainer, I want the prior-session fetcher to return an empty list rather than raise on transient Supabase errors, so that a database hiccup at session start does not block the user from starting their voice loop.
22. As a maintainer, I want the new memory feature to be forward-only with no backfill, so that historical conversations the user may have forgotten about are not retroactively LLM-summarised for a feature they did not have when those sessions were recorded.

### Maintainer — module shape

23. As a maintainer, I want the rich-context generation to be a pure function over a `Message` list, so that it can be tested with hand-built fixtures and an injected callable rather than requiring OpenAI in the loop.
24. As a maintainer, I want the identified-condition extraction to be a pure function over the same list, so that tests can assert "last successful `recommend_treatment` wins" without standing up the agent worker.
25. As a maintainer, I want the triage prompt builder to be a pure function over the prior-session list, so that prompt regression tests run instantly and do not require the LiveKit harness.
26. As a maintainer, I want the prior-session fetcher to be a separate function from the existing `list_for_user`, so that the `/conversations` API endpoint contract — which serves `ConversationSummary` — is not affected by the addition of `recall_context`.

## Implementation Decisions

**Storage shape — hybrid: one structured column plus enriched free-text.** Two new nullable columns are added to the `conversations` table: `identified_condition_id` (text), populated deterministically from the most recent successful `recommend_treatment` tool message at session-end, and `recall_context` (text), populated by the same LLM call that already produces `summary`. The existing `summary` field keeps its one-sentence shape unchanged so the history-list UI is not affected. The structured column exists because the *condition* is the load-bearing fact for safe follow-up; allowing an LLM to re-extract it from a free-text summary on every session start would re-introduce exactly the hallucination surface the existing safety hard rules are built to avoid.

**Single LLM call producing JSON.** The existing `_default_summary_fn` in `core.conversations` becomes `_default_summary_and_recall_fn` and emits JSON with two top-level keys: `summary` (one-sentence preview, unchanged shape) and `recall_context` (rich blob covering "what was discussed, what was recommended, outcomes reported"). Failure to parse JSON falls back to the existing `_truncated_fallback` for `summary` and leaves `recall_context` NULL — the next session simply sees no recall context for that conversation and opens normally. The function continues to accept the `summary_fn` injection point used by tests; the injection contract is widened to a tuple return.

**Deterministic identified-condition extraction.** A new pure function `extract_identified_condition(messages)` scans the message list in reverse for the most recent successful `tool` row with `tool_name == "recommend_treatment"` and returns the `condition_id` field of `tool_args`, validated against `core.conditions.CONDITIONS`. Zero LLM. Called by `end()` alongside the summary-and-recall function; the result is written into the new `identified_condition_id` column.

**Prior-session fetch — separate function.** A new `core.conversations.list_recent_with_recall(user, *, limit=3, supabase_token)` function returns the user's most recent conversations filtered to `identified_condition_id IS NOT NULL`, ordered `started_at DESC`. The return type is a new dataclass `PriorSession(started_at, identified_condition_id, recall_context)` — separate from `ConversationSummary` so the existing `/conversations` API endpoint contract is unaffected by the addition of `recall_context`.

**Prompt rendering — sibling helper, not extension of `build_system_prompt`.** A new `build_triage_system_prompt(prior_sessions)` lives next to the existing personalisation helper `build_system_prompt(preferred_name, preferences)` rather than extending its signature. The two surfaces deliberately stay separate so the existing disposition note ("triage does not personalise") does not get muddled by a "but it does memory" side door. The module-level `SYSTEM_PROMPT` constant is retired; the entrypoint computes the prompt per-session.

**Prompt block layout.** When `prior_sessions` is non-empty, the system prompt prepends a two-part block. The first part — "Most recent session" — names the identified condition and the recall context for the most recent prior session and is what drives the opener. The second part — "Earlier sessions (for pattern recognition, do not open by referencing these)" — lists up to two further sessions for the model's reasoning only. The block is followed by two new prompt rules: (a) if a "Most recent session" block is present, open by naming the condition and offering the fork between follow-up and new concern; (b) never quote treatment specifics, stretch durations, rep counts, or timelines from the recall block — new specifics this session must come fresh from `recommend_treatment`.

**Empty-input invariance.** With `prior_sessions == []`, `build_triage_system_prompt` returns a string byte-for-byte identical to today's static `SYSTEM_PROMPT`. This is the regression anchor for first-time users.

**Entrypoint wiring.** The agent worker's `entrypoint` fetches prior sessions via the new function before constructing the agent, then passes the result into `build_triage_system_prompt`. Best-effort: a fetch failure or a missing Supabase token degrades to `build_triage_system_prompt([])` and the user gets the default opener.

**Cardinality and filter — fixed at three with condition filter.** The fetch limit is three. Sessions without an identified condition are filtered out by the query. There is no "soft opener" branch for sessions that ended without identifying a condition: if the last condition-bearing session is recent it drives the opener; otherwise the agent opens normally.

**Safety — opener may name the condition, never numbers.** The two new prompt rules are explicit: the opener verbalises the condition (deterministic, from the structured column) but does not paraphrase any quantitative content from the `recall_context` blob. This keeps the existing hard rule ("never invent dosages, rep counts, or timelines") in force across sessions, not just within one.

**No backfill.** Existing rows keep NULL for both new columns and are filtered out of the prompt block by the fetch. Each user's recall feature lights up on the second session they end after this ships. No script, no retroactive LLM summarisation of historical conversations.

**Schema migration.** A single migration `0005_conversations_recall.sql` adds both columns as `text NULL`. Existing RLS policies on `conversations` already cover the row; no policy change needed because both new fields are user-scoped via the existing `user_id` row.

**No new tool registration.** `remember`/`recall` stay unregistered for the triage product, exactly as today. The episodic-memory tool surface is unchanged. The recall feature is a prompt-injection feature, not a tool feature.

## Testing Decisions

**What makes a good test here.** All tests target observable external behaviour: input → output of pure functions, or end-to-end-shaped assertions on the rendered system prompt and the persisted database fields. No tests assert on the structure of internal helper calls, on the JSON keys passed to OpenAI, or on private function names. The function-injection seam already used in `core.conversations` (the `summary_fn` callable parameter on `end()`) is the pattern for keeping the LLM out of unit tests; it is reused for the new tuple-returning callable.

**Module: `_default_summary_and_recall_fn` (unit).** Tests cover the JSON happy path (returns a `(summary, recall_context)` tuple where both are non-empty), the parse-failure fallback (malformed JSON yields `(_truncated_fallback(...), None)`), and the network-failure fallback (raised exception yields the same shape). Built with hand-constructed `Message` fixtures including `tool` rows for `recommend_treatment`. Prior art: the existing `summary_fn` injection tests in `apps/api/tests/` and `packages/core/tests/`.

**Module: `extract_identified_condition` (unit).** Tests cover: a single successful `recommend_treatment` call returns its `condition_id`; multiple successful calls return the *most recent* condition (last-recommend-wins); error tool calls (where the registry surfaced an error string instead of a payload) are skipped; an unknown `condition_id` (not in `CONDITIONS`) returns `None`; a message list with no `recommend_treatment` calls returns `None`. Pure function, fixture-driven, no Supabase, no LLM.

**Module: `build_triage_system_prompt` (unit).** Tests cover: empty input produces a string byte-for-byte equal to today's static `SYSTEM_PROMPT` (regression anchor — assert via the existing `SYSTEM_PROMPT` constant if retained, or against a snapshot otherwise); a single `PriorSession` produces a prompt containing the literal `identified_condition_id` and the literal `recall_context`; a three-element input produces both the "Most recent session" block and the "Earlier sessions" block with the latter two listed; the two new prompt rules ("name the condition, never the numbers" and "do not open by referencing earlier sessions") appear verbatim. Pure function, no fixtures beyond `PriorSession` instances.

**Module: integration assertion in the agent test harness.** With a stubbed `list_recent_with_recall` returning one fixture `PriorSession`, a session-start dry-run produces an `Agent` whose instructions string contains the fixture's `identified_condition_id`. Asserts the wiring path end-to-end without standing up LiveKit fully. Prior art: the agent integration tests for safety screening and tool-call forwarding under `apps/agent/tests/`.

**Skipped — out of unit-test scope.** No dedicated unit tests for `list_recent_with_recall` (it is one Supabase query and a projection; verifying the column filter and ordering is integration-test territory the repo does not currently have a harness for). No dedicated unit tests for the entrypoint glue (covered by the integration assertion above). No tests of OpenAI's actual response shape — the JSON parsing fallback path covers what happens when reality diverges.

## Out of Scope

- mem0 / `remember` / `recall` tool registration for the triage product. The conscious-recall surface stays unregistered; this PRD is purely about the prompt-injection memory layer.
- Backfill of historical conversations. Existing rows keep NULL and are filtered out.
- A user-facing memory opt-out toggle.
- Editing or redacting prior `recall_context` entries from the web app.
- Surfacing prior-session recall in the web UI (history page changes). The UI keeps reading the unchanged `summary` field.
- A "soft opener" mode for users whose most recent session ended without identifying a condition.
- Backfilling, recomputing, or migrating the existing `summary` field's content.
- Cross-user pattern recognition (cohort-level signals).
- Outcome capture as a structured column. Outcomes are captured organically in the transcript of the next session and rolled into that session's `recall_context` by the same generation step.
- Changing the cardinality from "last three" to a configurable parameter.
- Token-budget-driven dynamic cardinality.
- Reading prior `recommend_treatment` payloads back into the system prompt verbatim. Only the `condition_id` (deterministic) and the `recall_context` (LLM-generated, no numbers per the prompt rule) cross the session boundary.

## Further Notes

The disposition note in `apps/agent/agent/session.py` ("triage does not personalise; the cross-session 'remember about you' surface is an avoidable hallucination risk") was written about the mem0 episodic-memory tool surface and the structured-preferences personalisation. This PRD does not contradict it. Mem0 stays unregistered. The personalisation `build_system_prompt` helper stays bypassed. What this PRD adds is a *third* memory surface — prompt-time injection of structured triage-outcome facts — that the disposition note did not consider because it did not exist yet. The disposition note should be updated as part of the implementation to acknowledge the new surface and its safety constraints (condition-named, numbers-forbidden, last-three-condition-filtered) so a future contributor reading the file does not assume cross-session memory is universally rejected.

The "name the condition, never the numbers" rule in the opener is the load-bearing safety constraint. It is the bridge between today's hard rule ("never speak a treatment number that did not come from `recommend_treatment` for the matching condition") and the new cross-session surface. Implementation must put this rule in the prompt and the test must assert its presence verbatim — drift in the rule's wording is the failure mode that re-opens the hallucination risk the original disposition was guarding against.

The schema split (one structured column, one free-text) is also load-bearing. The structured `identified_condition_id` is what drives the opener; the free-text `recall_context` is supplementary context the model can reason over but is forbidden from quoting numbers from. If a future iteration moves the condition to a free-text-only representation, the safety story regresses.
