"""Integration test for `core.conversations` against a real Postgres.

What this test guarantees
-------------------------

The acceptance criteria call for an end-to-end check that:

* messages append-then-list returns rows in `created_at` order,
* `end` triggers summary generation when the message-count threshold
  is met (with a mocked LLM),
* RLS prevents one user from reading or writing another user's
  conversations and messages.

What this test does NOT do
--------------------------

We do not stand up a full Supabase stack inside a testcontainer (see
the same comment in :mod:`test_preferences_rls`). Instead we apply
both committed migrations to a plain Postgres container and exercise
RLS via ``SET LOCAL role = 'authenticated'`` and
``SET LOCAL request.jwt.claim.sub = '<uuid>'`` — the same predicate
shape PostgREST runs against in production.

The test is marked ``integration`` so the standard ``-m "not
integration"`` selector skips it. CI runs the integration suite
separately when Docker is available.
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
_PREFS_MIGRATION = _MIGRATIONS_DIR / "0001_user_preferences.sql"
_CONVS_MIGRATION = _MIGRATIONS_DIR / "0002_conversations.sql"


# Same shim as `test_preferences_rls`: replace Supabase's `auth.uid()`
# with one that reads `request.jwt.claim.sub` out of the session, so
# the migration's RLS predicates resolve under plain Postgres.
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
            cur.execute(_PREFS_MIGRATION.read_text())
            cur.execute(_CONVS_MIGRATION.read_text())
            cur.execute("create role authenticated nologin;")
            cur.execute(
                "grant select, insert, update, delete on public.user_preferences to authenticated;"
            )
            cur.execute(
                "grant select, insert, update, delete on public.conversations to authenticated;"
            )
            cur.execute("grant select, insert, update, delete on public.messages to authenticated;")
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


def test_append_then_list_returns_messages_in_order(
    pg_conn: psycopg.Connection[tuple[object, ...]],
) -> None:
    user_a = uuid4()
    user_b = uuid4()
    _seed_users(pg_conn, user_a=user_a, user_b=user_b)

    _set_jwt(pg_conn, user_a)
    with pg_conn.cursor() as cur:
        cur.execute(
            "insert into public.conversations (user_id) values (%s) returning id;",
            (str(user_a),),
        )
        row = cur.fetchone()
        assert row is not None
        conv_id = row[0]

        for content in ("hi", "hello", "what's up"):
            cur.execute(
                "insert into public.messages (conversation_id, role, content) values (%s, %s, %s);",
                (conv_id, "user", content),
            )
    pg_conn.commit()

    _set_jwt(pg_conn, user_a)
    with pg_conn.cursor() as cur:
        cur.execute(
            "select content from public.messages where conversation_id = %s "
            "order by created_at asc;",
            (conv_id,),
        )
        rows = [r[0] for r in cur.fetchall()]
    assert rows == ["hi", "hello", "what's up"]


def test_rls_isolates_conversations_between_users(
    pg_conn: psycopg.Connection[tuple[object, ...]],
) -> None:
    user_a = uuid4()
    user_b = uuid4()
    _seed_users(pg_conn, user_a=user_a, user_b=user_b)

    # User A starts a conversation and adds a message.
    _set_jwt(pg_conn, user_a)
    with pg_conn.cursor() as cur:
        cur.execute(
            "insert into public.conversations (user_id) values (%s) returning id;",
            (str(user_a),),
        )
        row = cur.fetchone()
        assert row is not None
        conv_id = row[0]
        cur.execute(
            "insert into public.messages (conversation_id, role, content) values (%s, %s, %s);",
            (conv_id, "user", "secret"),
        )
    pg_conn.commit()

    # User B sees zero conversations and zero messages.
    _set_jwt(pg_conn, user_b)
    with pg_conn.cursor() as cur:
        cur.execute("select count(*) from public.conversations;")
        cnt_conv = cur.fetchone()
        cur.execute("select count(*) from public.messages;")
        cnt_msg = cur.fetchone()
    assert cnt_conv is not None and cnt_conv[0] == 0
    assert cnt_msg is not None and cnt_msg[0] == 0


def test_rls_blocks_inserting_messages_into_other_users_conversation(
    pg_conn: psycopg.Connection[tuple[object, ...]],
) -> None:
    user_a = uuid4()
    user_b = uuid4()
    _seed_users(pg_conn, user_a=user_a, user_b=user_b)

    _set_jwt(pg_conn, user_a)
    with pg_conn.cursor() as cur:
        cur.execute(
            "insert into public.conversations (user_id) values (%s) returning id;",
            (str(user_a),),
        )
        row = cur.fetchone()
        assert row is not None
        conv_id = row[0]
    pg_conn.commit()

    # User B tries to inject a message into A's conversation. The RLS
    # `with check` clause refuses — Postgres raises rather than
    # silently inserting nothing on a direct INSERT. Either outcome is
    # acceptable; we accept both shapes here so the test stays robust
    # across Postgres versions and policy expression details.
    _set_jwt(pg_conn, user_b)
    with pg_conn.cursor() as cur:
        try:
            cur.execute(
                "insert into public.messages (conversation_id, role, content) values (%s, %s, %s);",
                (conv_id, "user", "i should not exist"),
            )
        except Exception:
            pg_conn.rollback()
        else:
            # Insert succeeded only if RLS allowed it — which it must
            # not for B writing to A's conversation. So this branch
            # implies a regression.
            pg_conn.commit()

    # Switch back to A and confirm no foreign messages snuck in.
    _set_jwt(pg_conn, user_a)
    with pg_conn.cursor() as cur:
        cur.execute(
            "select count(*) from public.messages where conversation_id = %s;",
            (conv_id,),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] == 0


def test_end_summary_path_with_mocked_llm_via_core_module(
    pg_conn: psycopg.Connection[tuple[object, ...]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drive `core.conversations.end` against the real database.

    Patches :func:`core.conversations.get_user_client` to return a
    psycopg-backed stub, and patches the summariser to skip the LLM.
    Asserts the resulting `summary` column is set.
    """
    user_a = uuid4()
    user_b = uuid4()
    _seed_users(pg_conn, user_a=user_a, user_b=user_b)

    # Seed a conversation with three messages so the threshold triggers.
    _set_jwt(pg_conn, user_a)
    with pg_conn.cursor() as cur:
        cur.execute(
            "insert into public.conversations (user_id) values (%s) returning id;",
            (str(user_a),),
        )
        row = cur.fetchone()
        assert row is not None
        conv_id_str = str(row[0])
        for role, content in (
            ("user", "hi"),
            ("assistant", "hello"),
            ("user", "weather?"),
        ):
            cur.execute(
                "insert into public.messages (conversation_id, role, content) values (%s, %s, %s);",
                (conv_id_str, role, content),
            )
    pg_conn.commit()

    # Drive `core.conversations.end` directly. The integration scope
    # here is the SQL behaviour, so we still mock the Supabase HTTP
    # client at its seam — the database state is what we read at the
    # end. A token-aware Supabase test stack would be substantially
    # more brittle than the signal warrants (see the same caveat in
    # `test_preferences_rls.py`).
    from core import conversations as core_conversations

    summary_called: dict[str, bool] = {"called": False}

    def _summary_fn(_msgs: list[core_conversations.Message]) -> str:
        summary_called["called"] = True
        return "Test summary."

    # Stub out the Supabase client. Each call returns a tiny shim that
    # reads/writes the live psycopg connection so the database
    # actually mutates and we can observe the row at the end.
    from typing import Any

    class _Reader:
        def __init__(self, conn: Any, conv_id: str) -> None:
            self.conn = conn
            self.conv_id = conv_id
            self._table: str | None = None
            self._payload: dict[str, Any] | None = None
            self._mode: str | None = None
            self._filters: list[tuple[str, str]] = []

        def table(self, name: str) -> _Reader:
            self._table = name
            self._filters = []
            self._payload = None
            self._mode = None
            return self

        def select(self, *_a: Any, **_kw: Any) -> _Reader:
            self._mode = "select"
            return self

        def update(self, payload: dict[str, Any]) -> _Reader:
            self._mode = "update"
            self._payload = payload
            return self

        def insert(self, _payload: dict[str, Any]) -> _Reader:
            return self

        def eq(self, col: str, val: str) -> _Reader:
            self._filters.append((col, val))
            return self

        def order(self, *_a: Any, **_kw: Any) -> _Reader:
            return self

        def range(self, *_a: Any, **_kw: Any) -> _Reader:
            return self

        def limit(self, *_a: Any, **_kw: Any) -> _Reader:
            return self

        def execute(self) -> Any:
            from unittest.mock import MagicMock

            assert self._table is not None
            with self.conn.cursor() as cur:
                # Re-bind RLS for this transaction; the same connection
                # may have been touched by other test code.
                cur.execute("set local role authenticated;")
                cur.execute(f"set local request.jwt.claim.sub = '{user_a}';")
                if self._mode == "select" and self._table == "messages":
                    cur.execute(
                        "select id, conversation_id, role, content, tool_name, "
                        "tool_args, tool_result, created_at from public.messages "
                        "where conversation_id = %s order by created_at asc;",
                        (self.conv_id,),
                    )
                    rows = cur.fetchall()
                    data = [
                        {
                            "id": str(r[0]),
                            "conversation_id": str(r[1]),
                            "role": r[2],
                            "content": r[3],
                            "tool_name": r[4],
                            "tool_args": r[5],
                            "tool_result": r[6],
                            "created_at": r[7].isoformat(),
                        }
                        for r in rows
                    ]
                    return MagicMock(data=data)
                if self._mode == "update" and self._table == "conversations":
                    assert self._payload is not None
                    sets = ", ".join(f"{k} = %s" for k in self._payload)
                    params = list(self._payload.values()) + [self.conv_id]
                    cur.execute(
                        f"update public.conversations set {sets} where id = %s;",
                        params,
                    )
                    self.conn.commit()
                    return MagicMock(data=[])
                return MagicMock(data=[])

    monkeypatch.setattr(
        "core.conversations.get_user_client",
        lambda *_a, **_kw: _Reader(pg_conn, conv_id_str),
    )

    core_conversations.end(
        UUID(conv_id_str),
        supabase_token="user-jwt",
        summary_fn=_summary_fn,
    )

    assert summary_called["called"] is True

    _set_jwt(pg_conn, user_a)
    with pg_conn.cursor() as cur:
        cur.execute(
            "select summary, ended_at from public.conversations where id = %s;",
            (conv_id_str,),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] == "Test summary."
    assert row[1] is not None
