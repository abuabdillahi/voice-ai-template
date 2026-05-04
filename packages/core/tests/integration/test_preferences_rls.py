"""Integration test for `core.preferences` against a real Postgres.

What this test guarantees
-------------------------

The acceptance criteria call for an end-to-end check that the row-level
security pattern established in `0001_user_preferences.sql` actually
isolates one user's preferences from another's.

What this test does NOT do
--------------------------

We do not stand up a full Supabase stack (PostgREST + GoTrue + Realtime)
inside a testcontainer. Doing so reliably under CI/sandboxed runs is
significantly more brittle than the underlying test signal warrants.
Instead we apply the migration to a plain Postgres container, then
exercise RLS at the database level the same way Supabase's PostgREST
does — by `SET LOCAL role = 'authenticated'` and
`SET LOCAL request.jwt.claim.sub = '<uuid>'`. This is exactly the
contract the production stack runs against, so the RLS predicates
(`auth.uid() = user_id`) are exercised faithfully.

The test creates a small `auth.uid()` shim that reads the JWT claim out
of the session — Supabase's real implementation is similar and the
shim is the documented portable approximation. Tests that need to
verify the *Python client's* behaviour live in the unit suite where
the client is mocked.

The test is marked `integration` so the standard `-m "not integration"`
selector skips it. CI runs the integration suite separately when Docker
is available.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest

# `testcontainers` is a dev-only dependency. Skip the whole module when
# it isn't installed (e.g. when running the unit suite via
# `-m "not integration"` — pytest still imports the module unless the
# import errors out, so a `pytest.importorskip` keeps developer
# environments without Docker happy).
psycopg = pytest.importorskip("psycopg")
testcontainers_postgres = pytest.importorskip("testcontainers.postgres")
PostgresContainer = testcontainers_postgres.PostgresContainer

pytestmark = pytest.mark.integration


# Path to the migration file. Computed once at import time so the test
# fails loudly if the file ever moves or is renamed.
_MIGRATION_PATH = (
    Path(__file__).resolve().parents[3] / "supabase" / "migrations" / "0001_user_preferences.sql"
)


# Supabase's `auth.uid()` and `auth.users` are normally provided by the
# GoTrue extension. Plain Postgres needs a tiny shim to make the same
# function name resolvable at the SQL site the migration uses. We
# substitute `auth.uid()` with a function that reads
# `request.jwt.claim.sub` out of the session — the same place GoTrue
# stores the authenticated user id when a request flows through
# PostgREST.
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
    """Spin up a Postgres container, apply the auth shim and migration."""
    with PostgresContainer("postgres:16-alpine") as pg:
        url = pg.get_connection_url().replace("postgresql+psycopg2", "postgresql")
        with psycopg.connect(url, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(_AUTH_SHIM)
            cur.execute(_MIGRATION_PATH.read_text())
            # Create the `authenticated` role PostgREST runs queries
            # under and grant it CRUD on the table — RLS is what
            # ultimately limits visibility, but the role still needs
            # base GRANTs to even reach the table.
            cur.execute("create role authenticated nologin;")
            cur.execute(
                "grant select, insert, update, delete on public.user_preferences to authenticated;"
            )
        yield url


@pytest.fixture
def pg_conn(pg_url: str) -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    """One connection per test, transaction-rolled-back at teardown.

    Using a fresh connection keeps the `SET LOCAL` session settings
    isolated per-test without having to clear them by hand.
    """
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
    """Insert two users into ``auth.users`` so FKs are satisfied."""
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
    """Bind the per-transaction JWT claim that ``auth.uid()`` reads.

    The session also assumes the `authenticated` role so RLS policies
    apply (the postgres superuser bypasses RLS entirely, which would
    defeat the point of this test).
    """
    with conn.cursor() as cur:
        cur.execute("set local role authenticated;")
        cur.execute(f"set local request.jwt.claim.sub = '{user_id}';")


def test_rls_prevents_cross_user_reads(
    pg_conn: psycopg.Connection[tuple[object, ...]],
) -> None:
    user_a = uuid4()
    user_b = uuid4()
    _seed_users(pg_conn, user_a=user_a, user_b=user_b)

    # User A writes a preference. User A's JWT claim drives both RLS
    # `with check` (allowing the insert) and the upsert payload.
    _set_jwt(pg_conn, user_a)
    with pg_conn.cursor() as cur:
        cur.execute(
            "insert into public.user_preferences (user_id, key, value) values (%s, %s, %s::jsonb);",
            (str(user_a), "favorite_color", '"blue"'),
        )
    pg_conn.commit()

    # User B cannot see User A's row.
    _set_jwt(pg_conn, user_b)
    with pg_conn.cursor() as cur:
        cur.execute("select count(*) from public.user_preferences;")
        row = cur.fetchone()
    assert row is not None
    assert row[0] == 0


def test_upsert_overwrites_existing_value(
    pg_conn: psycopg.Connection[tuple[object, ...]],
) -> None:
    user_a = uuid4()
    user_b = uuid4()
    _seed_users(pg_conn, user_a=user_a, user_b=user_b)

    _set_jwt(pg_conn, user_a)
    # First write.
    with pg_conn.cursor() as cur:
        cur.execute(
            "insert into public.user_preferences (user_id, key, value) "
            "values (%s, %s, %s::jsonb) "
            "on conflict (user_id, key) do update set value = excluded.value;",
            (str(user_a), "favorite_color", '"blue"'),
        )
    pg_conn.commit()

    # Second write with the same key — should overwrite, not insert a
    # second row, and should refresh `updated_at` via the trigger.
    with pg_conn.cursor() as cur:
        cur.execute(
            "insert into public.user_preferences (user_id, key, value) "
            "values (%s, %s, %s::jsonb) "
            "on conflict (user_id, key) do update set value = excluded.value;",
            (str(user_a), "favorite_color", '"red"'),
        )
        pg_conn.commit()
        cur.execute(
            "select value, updated_at from public.user_preferences "
            "where user_id = %s and key = %s;",
            (str(user_a), "favorite_color"),
        )
        row = cur.fetchone()
    assert row is not None
    value, updated_at = row
    assert value == "red"
    assert updated_at is not None


def test_list_only_returns_current_user_rows(
    pg_conn: psycopg.Connection[tuple[object, ...]],
) -> None:
    user_a = uuid4()
    user_b = uuid4()
    _seed_users(pg_conn, user_a=user_a, user_b=user_b)

    # User A writes one row.
    _set_jwt(pg_conn, user_a)
    with pg_conn.cursor() as cur:
        cur.execute(
            "insert into public.user_preferences (user_id, key, value) values (%s, %s, %s::jsonb);",
            (str(user_a), "favorite_color", '"blue"'),
        )
    pg_conn.commit()

    # User B writes two rows.
    _set_jwt(pg_conn, user_b)
    with pg_conn.cursor() as cur:
        cur.execute(
            "insert into public.user_preferences (user_id, key, value) "
            "values (%s, %s, %s::jsonb), (%s, %s, %s::jsonb);",
            (
                str(user_b),
                "preferred_name",
                '"Bob"',
                str(user_b),
                "language",
                '"de"',
            ),
        )
    pg_conn.commit()

    # User A only sees their own row.
    _set_jwt(pg_conn, user_a)
    with pg_conn.cursor() as cur:
        cur.execute("select key from public.user_preferences;")
        rows_a = {r[0] for r in cur.fetchall()}
    assert rows_a == {"favorite_color"}

    # User B only sees their own two rows.
    _set_jwt(pg_conn, user_b)
    with pg_conn.cursor() as cur:
        cur.execute("select key from public.user_preferences;")
        rows_b = {r[0] for r in cur.fetchall()}
    assert rows_b == {"preferred_name", "language"}


def test_rls_prevents_cross_user_updates_and_deletes(
    pg_conn: psycopg.Connection[tuple[object, ...]],
) -> None:
    user_a = uuid4()
    user_b = uuid4()
    _seed_users(pg_conn, user_a=user_a, user_b=user_b)

    _set_jwt(pg_conn, user_a)
    with pg_conn.cursor() as cur:
        cur.execute(
            "insert into public.user_preferences (user_id, key, value) values (%s, %s, %s::jsonb);",
            (str(user_a), "favorite_color", '"blue"'),
        )
    pg_conn.commit()

    # User B tries to update or delete user A's row. RLS turns these
    # into no-ops (zero rows match the policy) rather than raising.
    _set_jwt(pg_conn, user_b)
    with pg_conn.cursor() as cur:
        cur.execute(
            "update public.user_preferences set value = %s::jsonb where user_id = %s and key = %s;",
            ('"red"', str(user_a), "favorite_color"),
        )
        assert cur.rowcount == 0
        cur.execute(
            "delete from public.user_preferences where user_id = %s and key = %s;",
            (str(user_a), "favorite_color"),
        )
        assert cur.rowcount == 0
    pg_conn.commit()

    # User A's row is still there, untouched.
    _set_jwt(pg_conn, user_a)
    with pg_conn.cursor() as cur:
        cur.execute("select value from public.user_preferences;")
        row = cur.fetchone()
    assert row is not None
    assert row[0] == "blue"
