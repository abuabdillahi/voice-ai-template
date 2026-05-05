-- Issue 05: safety events audit log.
--
-- Persists every red-flag escalation as a row carrying the tier, the
-- source layer (regex / classifier / both), the matched flag ids, the
-- triggering utterance, the conversation id, the user id, and a
-- timestamp. The `messages` row for the triggering utterance is
-- already persisted by the existing transcript pipeline, so the audit
-- trail is complete: one event row plus the surrounding transcript
-- is enough to judge whether the escalation was correct.
--
-- This migration reuses the RLS pattern established in
-- `0001_user_preferences.sql` and `0002_conversations.sql`:
-- `auth.uid() = user_id` for read; insert under the user's JWT
-- context. A future clinician-reviewer role is anticipated but not
-- implemented here — the table is the seam.

create table if not exists public.safety_events (
    id uuid primary key default gen_random_uuid(),
    conversation_id uuid not null references public.conversations(id) on delete cascade,
    user_id uuid not null references auth.users(id) on delete cascade,
    tier text not null check (tier in ('emergent', 'urgent', 'clinician_soon')),
    source text not null check (source in ('regex', 'classifier', 'both')),
    matched_flags jsonb not null default '[]'::jsonb,
    utterance text not null,
    created_at timestamptz not null default now()
);

-- Future review queue ("most recent escalations across all users"):
-- (user_id, created_at desc) indexed so the per-user listing is
-- index-supported. The clinician-reviewer query will join through
-- conversations to get the transcript so a per-conversation fetch
-- index speeds that path too.
create index if not exists safety_events_user_created_at_idx
    on public.safety_events (user_id, created_at desc);

create index if not exists safety_events_conversation_id_idx
    on public.safety_events (conversation_id);

alter table public.safety_events enable row level security;

drop policy if exists "safety_events_select" on public.safety_events;
create policy "safety_events_select"
    on public.safety_events
    for select
    using (auth.uid() = user_id);

drop policy if exists "safety_events_insert" on public.safety_events;
create policy "safety_events_insert"
    on public.safety_events
    for insert
    with check (auth.uid() = user_id);

-- No update / delete policies — the audit log is append-only by
-- design. A clinician-reviewer role with read access lands in a
-- subsequent migration once the reviewer queue UI is built.
