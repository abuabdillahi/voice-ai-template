-- Issue 08: episodic memory via mem0.
--
-- Pre-creates the pgvector table mem0 writes memories to. Mem0's default
-- behaviour is to call `CREATE TABLE IF NOT EXISTS` on first use; we
-- ship the schema as a deterministic migration instead so production
-- deployments do not depend on the runtime path having DDL privileges.
--
-- The shape mirrors what `mem0.vector_stores.pgvector.PGVector.create_col`
-- produces (mem0ai 2.0.x): an `id UUID PRIMARY KEY`, a `vector` column
-- whose dimensionality matches the embedding model, and a `payload`
-- JSONB column that holds the memory text plus arbitrary metadata.
--
-- Importantly, mem0 does NOT carry user ownership in a typed column —
-- when callers invoke `Memory.add(..., user_id=str(user.id))`, mem0
-- writes the user id into `payload->>'user_id'`. The RLS predicates
-- below therefore filter on the JSONB extraction rather than a column,
-- which is the deviation from the canonical `auth.uid() = user_id`
-- pattern established in the earlier migrations. Behaviourally the
-- isolation is identical: a row whose payload's user_id does not match
-- the authenticated user is invisible to PostgREST queries.
--
-- Embedding dimensionality is pinned to 1536 to match OpenAI's
-- `text-embedding-3-small` (the mem0 default). Changing the embedding
-- model in `core.config` requires a follow-up migration that updates
-- the column type — there is no runtime path that resizes the column.

create table if not exists public.mem0_memories (
    id uuid primary key,
    vector extensions.vector(1536),
    payload jsonb not null default '{}'::jsonb
);

-- Index supporting cosine-similarity lookups used by mem0's
-- `Memory.search` (which is the read path behind `core.memory.recall`).
-- HNSW is mem0's default for pgvector and produces sub-millisecond
-- searches up to several million rows; the `IF NOT EXISTS` guard makes
-- the migration idempotent against environments where mem0 already
-- created the index in earlier development runs.
create index if not exists mem0_memories_hnsw_idx
    on public.mem0_memories
    using hnsw (vector extensions.vector_cosine_ops);

-- Mem0 also adds a GIN index over a lemmatised text representation of
-- the payload, which it uses for keyword-fallback search. Replicating
-- it here keeps the runtime DDL path a no-op.
create index if not exists mem0_memories_text_lemmatized_idx
    on public.mem0_memories
    using gin (to_tsvector('simple', payload->>'text_lemmatized'));

-- Index on the user_id JSONB extraction supports the per-user filtered
-- search mem0 issues when called as `Memory.search(query, user_id=...)`
-- and also the recent-memories listing the sidebar reads.
create index if not exists mem0_memories_user_id_idx
    on public.mem0_memories ((payload->>'user_id'));

alter table public.mem0_memories enable row level security;

-- RLS policies follow the canonical pattern but extract the user id
-- from the JSONB payload because mem0 does not write a typed column.
-- Each policy defends one operation; collectively they realise
-- "owner has full CRUD, nobody else can see anything" against the
-- `auth.uid()` of the calling session.

drop policy if exists "mem0_memories_select" on public.mem0_memories;
create policy "mem0_memories_select"
    on public.mem0_memories
    for select
    using (auth.uid()::text = payload->>'user_id');

drop policy if exists "mem0_memories_insert" on public.mem0_memories;
create policy "mem0_memories_insert"
    on public.mem0_memories
    for insert
    with check (auth.uid()::text = payload->>'user_id');

drop policy if exists "mem0_memories_update" on public.mem0_memories;
create policy "mem0_memories_update"
    on public.mem0_memories
    for update
    using (auth.uid()::text = payload->>'user_id')
    with check (auth.uid()::text = payload->>'user_id');

drop policy if exists "mem0_memories_delete" on public.mem0_memories;
create policy "mem0_memories_delete"
    on public.mem0_memories
    for delete
    using (auth.uid()::text = payload->>'user_id');
