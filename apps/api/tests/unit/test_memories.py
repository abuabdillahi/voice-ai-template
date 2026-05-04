"""Tests for the `/memories/recent` route.

Asserts the externally-observable behaviour: status codes, response
shape, and that the user's bearer token reaches `core.memory.list_recent`
unchanged. The underlying mem0 round-trip is mocked at the module
boundary — the integration test in `core` covers the database path.
"""

from __future__ import annotations

from unittest.mock import patch

from core.auth import User
from core.memory import Memory
from fastapi.testclient import TestClient


def test_recent_memories_returns_rows_when_authenticated(
    authed_client: TestClient,
    fake_user: User,
) -> None:
    fake_rows = [
        Memory(id="mem-1", content="is learning Spanish"),
        Memory(id="mem-2", content="has a daughter named Maya"),
    ]
    with patch("api.routes.core_memory.list_recent", return_value=fake_rows) as listed:
        resp = authed_client.get(
            "/memories/recent",
            headers={"Authorization": "Bearer user-jwt"},
        )
    assert resp.status_code == 200
    assert resp.json() == {
        "memories": [
            {"id": "mem-1", "content": "is learning Spanish"},
            {"id": "mem-2", "content": "has a daughter named Maya"},
        ]
    }
    listed.assert_called_once()
    args, kwargs = listed.call_args
    assert args[0] == fake_user
    assert kwargs == {"limit": 10, "supabase_token": "user-jwt"}


def test_recent_memories_returns_empty_list_when_user_has_no_rows(
    authed_client: TestClient,
) -> None:
    with patch("api.routes.core_memory.list_recent", return_value=[]):
        resp = authed_client.get(
            "/memories/recent",
            headers={"Authorization": "Bearer user-jwt"},
        )
    assert resp.status_code == 200
    assert resp.json() == {"memories": []}


def test_recent_memories_returns_401_without_token(client: TestClient) -> None:
    resp = client.get("/memories/recent")
    assert resp.status_code == 401
    assert resp.headers.get("WWW-Authenticate") == "Bearer"
