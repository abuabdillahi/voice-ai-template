"""Integration test for ``safety_events`` RLS isolation.

Mirrors the pattern in :mod:`tests.integration.test_preferences_rls`
and :mod:`tests.integration.test_conversations_rls`: apply the auth
shim and the migrations to a plain Postgres container, then drive RLS
the same way Supabase's PostgREST does.

The test guarantees: user A cannot read user B's safety events; user A
cannot insert an event with user B's user_id.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest

psycopg = pytest.importorskip("psycopg")
testcontainers_postgres = pytest.importorskip("testcontainers.postgres")
PostgresContainer = testcontainers_postgres.PostgresContainer

pytestmark = pytest.mark.integration


_MIGRATIONS_DIR = Path(__file__).resolve().parents[4] / "supabase" / "migrations"


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
    with PostgresContainer("postgres:16-alpine") as pg:
        url = pg.get_connection_url().replace("postgresql+psycopg2", "postgresql")
        with psycopg.connect(url, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(_AUTH_SHIM)
            # safety_events has FKs to conversations and auth.users —
            # apply the prerequisite migrations in order.
            for name in (
                "0001_user_preferences.sql",
                "0002_conversations.sql",
                "0004_safety_events.sql",
            ):
                cur.execute((_MIGRATIONS_DIR / name).read_text())
            cur.execute("create role authenticated nologin;")
            cur.execute(
                "grant select, insert, update, delete on public.user_preferences to authenticated;"
            )
            cur.execute(
                "grant select, insert, update, delete on public.conversations to authenticated;"
            )
            cur.execute("grant select, insert, update, delete on public.messages to authenticated;")
            cur.execute(
                "grant select, insert, update, delete on public.safety_events to authenticated;"
            )
        yield url


@pytest.fixture
def pg_conn(pg_url: str) -> Iterator[psycopg.Connection[tuple[object, ...]]]:
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


def _seed_conversation(
    conn: psycopg.Connection[tuple[object, ...]],
    user_id: UUID,
) -> UUID:
    """Insert a conversation under the JWT scope and return its id."""
    _set_jwt(conn, user_id)
    with conn.cursor() as cur:
        cur.execute(
            "insert into public.conversations (user_id) values (%s) returning id;",
            (str(user_id),),
        )
        row = cur.fetchone()
    conn.commit()
    assert row is not None
    return UUID(str(row[0]))


def test_rls_prevents_cross_user_reads(
    pg_conn: psycopg.Connection[tuple[object, ...]],
) -> None:
    user_a = uuid4()
    user_b = uuid4()
    _seed_users(pg_conn, user_a=user_a, user_b=user_b)
    conv_a = _seed_conversation(pg_conn, user_a)

    # User A inserts an event.
    _set_jwt(pg_conn, user_a)
    with pg_conn.cursor() as cur:
        cur.execute(
            "insert into public.safety_events "
            "(conversation_id, user_id, tier, source, matched_flags, utterance) "
            "values (%s, %s, %s, %s, %s::jsonb, %s);",
            (
                str(conv_a),
                str(user_a),
                "emergent",
                "regex",
                '["chest_pain"]',
                "I am having chest pain",
            ),
        )
    pg_conn.commit()

    # User B cannot see the row.
    _set_jwt(pg_conn, user_b)
    with pg_conn.cursor() as cur:
        cur.execute("select count(*) from public.safety_events;")
        row = cur.fetchone()
    assert row is not None
    assert row[0] == 0


def test_rls_prevents_inserting_with_other_users_id(
    pg_conn: psycopg.Connection[tuple[object, ...]],
) -> None:
    user_a = uuid4()
    user_b = uuid4()
    _seed_users(pg_conn, user_a=user_a, user_b=user_b)
    conv_a = _seed_conversation(pg_conn, user_a)

    # User B authenticates but tries to insert a row owned by user A —
    # the RLS `with check` predicate must deny it.
    _set_jwt(pg_conn, user_b)
    with pytest.raises(Exception), pg_conn.cursor() as cur:  # noqa: B017 — RLS denial surfaces as psycopg error
        cur.execute(
            "insert into public.safety_events "
            "(conversation_id, user_id, tier, source, matched_flags, utterance) "
            "values (%s, %s, %s, %s, %s::jsonb, %s);",
            (
                str(conv_a),
                str(user_a),  # Note: not user_b's id.
                "emergent",
                "regex",
                '["chest_pain"]',
                "trying to spoof",
            ),
        )
    pg_conn.rollback()

    # User A still has zero events recorded by anyone.
    _set_jwt(pg_conn, user_a)
    with pg_conn.cursor() as cur:
        cur.execute("select count(*) from public.safety_events where user_id = %s;", (str(user_a),))
        row = cur.fetchone()
    assert row is not None
    assert row[0] == 0


def test_listing_returns_only_current_users_events(
    pg_conn: psycopg.Connection[tuple[object, ...]],
) -> None:
    user_a = uuid4()
    user_b = uuid4()
    _seed_users(pg_conn, user_a=user_a, user_b=user_b)
    conv_a = _seed_conversation(pg_conn, user_a)
    conv_b = _seed_conversation(pg_conn, user_b)

    _set_jwt(pg_conn, user_a)
    with pg_conn.cursor() as cur:
        cur.execute(
            "insert into public.safety_events "
            "(conversation_id, user_id, tier, source, matched_flags, utterance) "
            "values (%s, %s, %s, %s, %s::jsonb, %s);",
            (str(conv_a), str(user_a), "emergent", "regex", "[]", "alpha"),
        )
    pg_conn.commit()

    _set_jwt(pg_conn, user_b)
    with pg_conn.cursor() as cur:
        cur.execute(
            "insert into public.safety_events "
            "(conversation_id, user_id, tier, source, matched_flags, utterance) "
            "values (%s, %s, %s, %s, %s::jsonb, %s), "
            "(%s, %s, %s, %s, %s::jsonb, %s);",
            (
                str(conv_b),
                str(user_b),
                "urgent",
                "regex",
                "[]",
                "beta",
                str(conv_b),
                str(user_b),
                "clinician_soon",
                "regex",
                "[]",
                "gamma",
            ),
        )
    pg_conn.commit()

    _set_jwt(pg_conn, user_a)
    with pg_conn.cursor() as cur:
        cur.execute("select utterance from public.safety_events;")
        utterances_a = {row[0] for row in cur.fetchall()}
    assert utterances_a == {"alpha"}

    _set_jwt(pg_conn, user_b)
    with pg_conn.cursor() as cur:
        cur.execute("select utterance from public.safety_events;")
        utterances_b = {row[0] for row in cur.fetchall()}
    assert utterances_b == {"beta", "gamma"}
