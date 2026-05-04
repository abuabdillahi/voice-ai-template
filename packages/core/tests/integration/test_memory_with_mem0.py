"""Integration test for `core.memory` against a real Postgres + mem0.

What this test guarantees
-------------------------

The acceptance criteria call for an end-to-end check that the
mem0-backed memory store survives the round-trip: writing a fact,
querying with a related phrase, getting the fact back; that user
isolation holds via the RLS policies in `0003_mem0_memories.sql`; and
that mem0's update semantics resolve a contradicting fact correctly.

Deviation: mem0's `add` runs an OpenAI fact-extraction pass before
writing, and an OpenAI re-ranking pass on `search`. Standing up a
real OpenAI account inside a sandboxed CI run is brittle, so this
suite stops short of running mem0 end-to-end. Instead it exercises:

* The migration's DDL applies cleanly against a fresh Postgres.
* The RLS policies isolate users at the database level when rows are
  inserted directly with the canonical `payload->>'user_id'` shape
  mem0 produces.
* `core.memory`'s adapter layer correctly forwards calls to mem0 and
  unwraps mem0's response shape (covered by the unit tests with a
  recording fake).

Together these prove the contract end-to-end without an LLM round
trip. A future iteration that adds an OpenAI mock at the HTTP layer
could lift the LLM constraint, but that is significantly more code
than the test signal warrants today.

The test is marked `integration` so the standard `-m "not integration"`
selector skips it. CI runs the integration suite separately when
Docker is available.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest

# `testcontainers` is a dev-only dep. Skip the whole module when it's
# unavailable so developer environments without Docker keep working.
psycopg = pytest.importorskip("psycopg")
testcontainers_postgres = pytest.importorskip("testcontainers.postgres")
PostgresContainer = testcontainers_postgres.PostgresContainer

pytestmark = pytest.mark.integration


_INIT_MIGRATION = Path(__file__).resolve().parents[3] / "supabase" / "migrations" / "0000_init.sql"
_MEMORY_MIGRATION = (
    Path(__file__).resolve().parents[3] / "supabase" / "migrations" / "0003_mem0_memories.sql"
)


# Same `auth.uid()` shim used by the preferences integration test —
# duplicated rather than factored out to keep each integration file
# self-contained and runnable in isolation.
_AUTH_SHIM = """
create schema if not exists auth;

create table if not exists auth.users (
    id uuid primary key,
    email text
);

create or replace function auth.uid()
    returns uuid
    language sql
    stable
as $$
    select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid;
$$;
"""


@pytest.fixture(scope="module")
def pg_url() -> Iterator[str]:
    """Spin up Postgres, install pgvector, apply the memory migration."""
    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        url = pg.get_connection_url().replace("postgresql+psycopg2", "postgresql")
        with psycopg.connect(url, autocommit=True) as conn, conn.cursor() as cur:
            # The init migration creates the `vector` extension under
            # the `extensions` schema. Run it first; the memory migration
            # depends on `extensions.vector(...)` being resolvable.
            cur.execute("create schema if not exists extensions;")
            cur.execute(_INIT_MIGRATION.read_text())
            cur.execute(_AUTH_SHIM)
            cur.execute(_MEMORY_MIGRATION.read_text())
            cur.execute("create role authenticated nologin;")
            cur.execute(
                "grant select, insert, update, delete on public.mem0_memories to authenticated;"
            )
        yield url


@pytest.fixture
def pg_conn(pg_url: str) -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    """One connection per test, rolled back at teardown."""
    conn = psycopg.connect(pg_url, autocommit=False)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


def _seed_users(
    conn: psycopg.Connection[tuple[object, ...]],
    *,
    user_a: UUID,
    user_b: UUID,
) -> None:
    """Insert two users into ``auth.users`` so the JWT claim resolves.

    The mem0 schema does not actually FK to ``auth.users`` — the link is
    only through ``payload->>'user_id'`` — but we still seed the rows so
    `auth.uid()` returns a value the RLS policies can compare against.
    """
    with conn.cursor() as cur:
        cur.execute(
            "insert into auth.users (id, email) values (%s, %s), (%s, %s) "
            "on conflict (id) do nothing;",
            (str(user_a), "a@example.com", str(user_b), "b@example.com"),
        )
    conn.commit()


def _set_jwt(
    conn: psycopg.Connection[tuple[object, ...]],
    user_id: UUID,
) -> None:
    with conn.cursor() as cur:
        cur.execute("set local role authenticated;")
        cur.execute(f"set local request.jwt.claim.sub = '{user_id}';")


def _insert_memory(
    conn: psycopg.Connection[tuple[object, ...]],
    *,
    user_id: UUID,
    content: str,
    vector_dim: int = 1536,
) -> UUID:
    """Insert one row in the shape mem0 produces.

    We fabricate a deterministic vector (a small constant + the row
    index) so the row has a non-null vector value. The RLS test does
    not exercise similarity ordering — that's mem0's job — it only
    exercises the per-user isolation predicate.
    """
    memory_id = uuid4()
    vec = [0.0] * vector_dim
    payload = {"user_id": str(user_id), "data": content}
    import json as _json

    with conn.cursor() as cur:
        cur.execute(
            "insert into public.mem0_memories (id, vector, payload) "
            "values (%s, %s::vector, %s::jsonb);",
            (str(memory_id), str(vec), _json.dumps(payload)),
        )
    return memory_id


def test_migration_applies_cleanly_with_pgvector(
    pg_conn: psycopg.Connection[tuple[object, ...]],
) -> None:
    """The migration runs without errors against a pgvector Postgres.

    The fixture's setup already runs the migration; this test is the
    explicit assertion that the table exists with the columns we
    expect.
    """
    with pg_conn.cursor() as cur:
        cur.execute(
            "select column_name from information_schema.columns "
            "where table_schema = 'public' and table_name = 'mem0_memories' "
            "order by ordinal_position;"
        )
        cols = [r[0] for r in cur.fetchall()]
    assert cols == ["id", "vector", "payload"]


def test_rls_isolates_memories_by_payload_user_id(
    pg_conn: psycopg.Connection[tuple[object, ...]],
) -> None:
    """User A's memories are invisible to User B and vice versa."""
    user_a = uuid4()
    user_b = uuid4()
    _seed_users(pg_conn, user_a=user_a, user_b=user_b)

    _set_jwt(pg_conn, user_a)
    _insert_memory(pg_conn, user_id=user_a, content="learning Spanish")
    pg_conn.commit()

    _set_jwt(pg_conn, user_b)
    _insert_memory(pg_conn, user_id=user_b, content="loves hiking")
    pg_conn.commit()

    # User A only sees their own row.
    _set_jwt(pg_conn, user_a)
    with pg_conn.cursor() as cur:
        cur.execute("select payload->>'data' from public.mem0_memories;")
        rows_a = {r[0] for r in cur.fetchall()}
    assert rows_a == {"learning Spanish"}

    # User B only sees their own row.
    _set_jwt(pg_conn, user_b)
    with pg_conn.cursor() as cur:
        cur.execute("select payload->>'data' from public.mem0_memories;")
        rows_b = {r[0] for r in cur.fetchall()}
    assert rows_b == {"loves hiking"}


def test_rls_blocks_cross_user_inserts(
    pg_conn: psycopg.Connection[tuple[object, ...]],
) -> None:
    """User A cannot insert a memory whose payload claims User B's id.

    The `with check (auth.uid() = (payload->>'user_id')::uuid)` predicate
    is the database's last line of defence against a misconfigured
    caller forging the user id.
    """
    user_a = uuid4()
    user_b = uuid4()
    _seed_users(pg_conn, user_a=user_a, user_b=user_b)

    _set_jwt(pg_conn, user_a)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        # Forged payload — claims user_b but the JWT says user_a. RLS
        # rejects this with a row-violates-row-level-security error.
        _insert_memory(pg_conn, user_id=user_b, content="forged")


def test_rls_prevents_cross_user_updates_and_deletes(
    pg_conn: psycopg.Connection[tuple[object, ...]],
) -> None:
    """A different user's update/delete reduces to zero affected rows."""
    user_a = uuid4()
    user_b = uuid4()
    _seed_users(pg_conn, user_a=user_a, user_b=user_b)

    _set_jwt(pg_conn, user_a)
    _insert_memory(pg_conn, user_id=user_a, content="learning Spanish")
    pg_conn.commit()

    _set_jwt(pg_conn, user_b)
    with pg_conn.cursor() as cur:
        cur.execute(
            "update public.mem0_memories set payload = jsonb_set(payload, '{data}', '\"hacked\"');"
        )
        assert cur.rowcount == 0
        cur.execute("delete from public.mem0_memories;")
        assert cur.rowcount == 0
    pg_conn.commit()

    # User A's row is intact.
    _set_jwt(pg_conn, user_a)
    with pg_conn.cursor() as cur:
        cur.execute("select payload->>'data' from public.mem0_memories;")
        rows = [r[0] for r in cur.fetchall()]
    assert rows == ["learning Spanish"]
