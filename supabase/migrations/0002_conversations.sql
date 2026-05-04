-- Issue 09: conversation transcripts.
--
-- Persists every voice conversation as a parent `conversations` row plus
-- one `messages` row per turn (user, assistant, or tool call). The web
-- app's history page reads these tables; the agent worker writes them
-- via `core.conversations`.
--
-- This migration reuses the RLS pattern established in
-- `0001_user_preferences.sql` verbatim for `conversations` (the
-- `auth.uid() = user_id` predicate runs against a column on the row
-- being checked). `messages` does not carry a `user_id` column —
-- ownership is implicit via the `conversation_id` FK — so its RLS
-- predicate joins through `conversations` to enforce user scoping.
--
-- Audio recordings are explicitly out of scope per the PRD; only text
-- transcripts are persisted.

create table if not exists public.conversations (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    started_at timestamptz not null default now(),
    ended_at timestamptz null,
    summary text null,
    metadata jsonb not null default '{}'::jsonb
);

create index if not exists conversations_user_started_at_idx
    on public.conversations (user_id, started_at desc);

alter table public.conversations enable row level security;

drop policy if exists "conversations_select" on public.conversations;
create policy "conversations_select"
    on public.conversations
    for select
    using (auth.uid() = user_id);

drop policy if exists "conversations_insert" on public.conversations;
create policy "conversations_insert"
    on public.conversations
    for insert
    with check (auth.uid() = user_id);

drop policy if exists "conversations_update" on public.conversations;
create policy "conversations_update"
    on public.conversations
    for update
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

drop policy if exists "conversations_delete" on public.conversations;
create policy "conversations_delete"
    on public.conversations
    for delete
    using (auth.uid() = user_id);


create table if not exists public.messages (
    id uuid primary key default gen_random_uuid(),
    conversation_id uuid not null references public.conversations(id) on delete cascade,
    role text not null check (role in ('user', 'assistant', 'tool')),
    content text not null,
    tool_name text null,
    tool_args jsonb null,
    tool_result jsonb null,
    created_at timestamptz not null default now()
);

create index if not exists messages_conversation_created_at_idx
    on public.messages (conversation_id, created_at);

alter table public.messages enable row level security;

-- Messages do not carry a user_id column; their owner is the user_id of
-- the parent conversation. The RLS predicate joins through
-- conversations so PostgREST runs the same scoping check on every
-- operation. The subquery is small (single-row pk lookup) and fully
-- index-supported.

drop policy if exists "messages_select" on public.messages;
create policy "messages_select"
    on public.messages
    for select
    using (
        auth.uid() = (
            select c.user_id
            from public.conversations c
            where c.id = messages.conversation_id
        )
    );

drop policy if exists "messages_insert" on public.messages;
create policy "messages_insert"
    on public.messages
    for insert
    with check (
        auth.uid() = (
            select c.user_id
            from public.conversations c
            where c.id = messages.conversation_id
        )
    );

drop policy if exists "messages_update" on public.messages;
create policy "messages_update"
    on public.messages
    for update
    using (
        auth.uid() = (
            select c.user_id
            from public.conversations c
            where c.id = messages.conversation_id
        )
    )
    with check (
        auth.uid() = (
            select c.user_id
            from public.conversations c
            where c.id = messages.conversation_id
        )
    );

drop policy if exists "messages_delete" on public.messages;
create policy "messages_delete"
    on public.messages
    for delete
    using (
        auth.uid() = (
            select c.user_id
            from public.conversations c
            where c.id = messages.conversation_id
        )
    );
