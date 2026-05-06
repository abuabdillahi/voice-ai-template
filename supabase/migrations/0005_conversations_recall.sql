-- Ergo triage recall: persist identified condition and recall context.
--
-- Adds two nullable columns to `conversations` so the agent can drive a
-- safe follow-up opener on the user's next session:
--
--   * `identified_condition_id` — the `condition_id` of the most recent
--     successful `recommend_treatment` tool message, extracted
--     deterministically at session-end. This is the *load-bearing* fact
--     for the next session's opener; allowing an LLM to re-extract it
--     from a free-text summary would re-introduce hallucination risk
--     the system prompt's hard rules are built to avoid.
--   * `recall_context` — a richer free-text blob produced by the same
--     LLM call that already mints `summary`, covering what was
--     discussed, what was recommended, and any user-reported outcomes.
--
-- The existing one-sentence `summary` field keeps its current shape;
-- the history-list UI reads it directly and must not regress. The new
-- columns are populated only on session end and are nullable so
-- existing rows and short / failed sessions stay valid.
--
-- Existing RLS policies on `conversations` (see
-- `0002_conversations.sql`) already cover both columns via the row's
-- `user_id`; no policy change is required because both new fields are
-- user-scoped via the existing predicates.

alter table public.conversations
    add column if not exists identified_condition_id text null,
    add column if not exists recall_context text null;
