-- Initial migration: enable pgvector for the memory layer added in
-- issue 09. Application tables (preferences, conversations, messages,
-- memory) land in subsequent migrations and depend on this extension
-- being available. Auth tables are managed by Supabase itself.

create extension if not exists "vector" with schema "extensions";

-- Future migrations build on this baseline. RLS policies for every
-- user-scoped table follow the canonical pattern:
--
--   alter table <table> enable row level security;
--   create policy "<table>_owner" on <table>
--       for all
--       using (auth.uid() = user_id)
--       with check (auth.uid() = user_id);
