-- Issue 02: extend `safety_events.source` to include 'model'.
--
-- The model-callable `escalate` tool can now drive a teardown that
-- writes a `safety_events` row with `source='model'`, an empty
-- `matched_flags` array, and an empty `utterance` (the free-text
-- `reason` lives in structured logs only — see
-- `_persist_safety_event_from_model` in `apps/agent/agent/session.py`).
--
-- The previous check was `source in ('regex', 'classifier', 'both')`
-- (see `0004_safety_events.sql`); this migration drops that
-- constraint and reinstates it with 'model' added. The reviewer
-- queue (post-MVP) reads `source` to disambiguate which layer judged
-- the escalation.

alter table public.safety_events
    drop constraint if exists safety_events_source_check;

alter table public.safety_events
    add constraint safety_events_source_check
    check (source in ('regex', 'classifier', 'both', 'model'));
