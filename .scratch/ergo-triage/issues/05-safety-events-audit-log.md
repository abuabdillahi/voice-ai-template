# Issue 05: Safety events audit log

Status: needs-triage

## Parent

`.scratch/ergo-triage/PRD.md`

## What to build

Persist every red-flag trigger as a row in a new `safety_events` table so a clinician reviewer can audit escalations after the fact. After this slice, every safety hook firing — currently only the regex layer; the classifier source is added in slice 06 — produces a row carrying the tier, the source layer, the matched flags, the utterance text, the conversation id, the user id, and a timestamp. The `messages` row for the triggering utterance is already persisted by the existing transcript pipeline, so the audit trail is complete: one event row plus the surrounding transcript is enough to judge whether the escalation was correct.

The slice adds the `safety_events` table via migration `0004_safety_events.sql` with row-level security mirroring the precedent of `conversations` and `messages`: `auth.uid() = user_id` for read; insert under the user's JWT context. A future clinician-reviewer role is anticipated but not implemented here — the table itself is the seam.

`core.safety_events` is added as a thin deep module — typed insert, typed read for the user's own events. The safety hook in the agent worker is amended to call the insert path on every tier-1 or tier-2 trigger, in addition to playing the script and ending the session.

## Acceptance criteria

- [ ] Migration `supabase/migrations/0004_safety_events.sql` creates the `safety_events` table with columns: `id uuid pk default gen_random_uuid()`, `conversation_id uuid not null references conversations(id) on delete cascade`, `user_id uuid not null references auth.users(id) on delete cascade`, `tier text not null check (tier in ('emergent','urgent','clinician_soon'))`, `source text not null check (source in ('regex','classifier','both'))`, `matched_flags jsonb not null default '[]'::jsonb`, `utterance text not null`, `created_at timestamptz not null default now()`.
- [ ] RLS is enabled on `safety_events`. Read policy: `auth.uid() = user_id`. Insert policy: `auth.uid() = user_id` (matches the existing `conversations` and `messages` table policies). Indexes: `(user_id, created_at desc)` for the future review queue, `(conversation_id)` for transcript correlation.
- [ ] `core.safety_events` module exposes `record(conversation_id, user_id, tier, source, matched_flags, utterance, supabase_token) -> SafetyEvent` and `list_for_user(user, supabase_token) -> list[SafetyEvent]`. Insert and read are scoped under the user's JWT, mirroring the `core.preferences` and `core.conversations` patterns.
- [ ] Unit tests cover the module surface: insert returns the persisted row shape; list returns rows ordered by `created_at desc`.
- [ ] Integration test against a real Postgres asserts RLS isolation — user A cannot read user B's events, user A cannot insert an event with user B's `user_id`. Mirrors `tests/integration/test_preferences_rls.py` and `tests/integration/test_conversations_rls.py`.
- [ ] The safety hook in `apps/agent/agent/session.py` is amended to call `core.safety_events.record(...)` on every tier-1 or tier-2 regex trigger, with the source argument set to `regex`. Failure to insert is logged but does not prevent the escalation script or session end — persistence is best-effort, the safety floor is not.
- [ ] An agent integration test asserts that a scripted tier-1 user utterance produces exactly one `safety_events` row with the expected tier, source `regex`, and the matched flags.
- [ ] No regression in the transcript persistence pipeline. The `messages` row for the triggering utterance still lands.

## Blocked by

`.scratch/ergo-triage/issues/04-safety-regex-screen-and-escalate.md`
