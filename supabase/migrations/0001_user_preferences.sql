-- Issue 07: structured user preferences.
--
-- Persists named per-user preferences across sessions and devices.
-- The agent reads/writes these via `set_preference` and `get_preference`
-- tools (see `core.tools.preferences`); the API exposes a `GET /preferences`
-- read-only listing for the "what I remember about you" sidebar.
--
-- This migration also establishes the canonical RLS pattern that every
-- subsequent user-scoped table (conversations, messages, mem0 memories)
-- reuses verbatim. The shape is intentionally boring:
--
--   1. (user_id, ...) primary key referencing auth.users.
--   2. ON DELETE CASCADE so deleting a user wipes their data.
--   3. RLS enabled, with a single policy permitting full CRUD when
--      `auth.uid() = user_id` (and the same predicate in WITH CHECK).
--   4. updated_at maintained by a trigger.

create table if not exists public.user_preferences (
    user_id uuid not null references auth.users(id) on delete cascade,
    key text not null,
    value jsonb not null,
    updated_at timestamptz not null default now(),
    primary key (user_id, key)
);

alter table public.user_preferences enable row level security;

-- A single policy covering all four operations is the minimal expression
-- of the "owner has full CRUD, nobody else can see anything" rule.
-- Splitting into per-operation policies (the AC asks for select/insert/
-- update/delete) is equivalent at the DB level — each is just sugar for
-- a row-level predicate. We keep four named policies so downstream
-- maintainers can tweak any one operation in isolation without rewriting
-- the others.

drop policy if exists "user_preferences_select" on public.user_preferences;
create policy "user_preferences_select"
    on public.user_preferences
    for select
    using (auth.uid() = user_id);

drop policy if exists "user_preferences_insert" on public.user_preferences;
create policy "user_preferences_insert"
    on public.user_preferences
    for insert
    with check (auth.uid() = user_id);

drop policy if exists "user_preferences_update" on public.user_preferences;
create policy "user_preferences_update"
    on public.user_preferences
    for update
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

drop policy if exists "user_preferences_delete" on public.user_preferences;
create policy "user_preferences_delete"
    on public.user_preferences
    for delete
    using (auth.uid() = user_id);

-- Refresh `updated_at` on every UPDATE. Defined inline rather than in a
-- shared utilities migration so this file is self-contained — later
-- tables that want the same behaviour can reuse the function (it lives
-- in the public schema with a stable name).

create or replace function public.set_updated_at()
    returns trigger
    language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists user_preferences_set_updated_at on public.user_preferences;
create trigger user_preferences_set_updated_at
    before update on public.user_preferences
    for each row
    execute function public.set_updated_at();
