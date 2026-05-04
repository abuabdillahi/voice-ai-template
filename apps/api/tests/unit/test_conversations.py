"""Tests for the `/conversations` and `/conversations/{id}` routes.

Asserts the externally-observable behaviour: status codes, response
shape, and that the user's bearer token reaches the core layer
unchanged. The underlying Supabase round-trip is mocked at the
`core.conversations` boundary — the integration test in `core` covers
the real database path.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch
from uuid import UUID, uuid4

from core.auth import User
from core.conversations import Conversation, ConversationSummary, Message
from fastapi.testclient import TestClient


def _summary(**overrides: object) -> ConversationSummary:
    base = {
        "id": uuid4(),
        "started_at": datetime(2026, 5, 4, 12, 0, tzinfo=UTC),
        "ended_at": datetime(2026, 5, 4, 12, 5, tzinfo=UTC),
        "summary": "About the weather",
        "message_count": 4,
    }
    base.update(overrides)
    return ConversationSummary(**base)  # type: ignore[arg-type]


def test_list_conversations_returns_rows_when_authenticated(
    authed_client: TestClient,
    fake_user: User,
) -> None:
    rows = [_summary(), _summary(summary=None, ended_at=None, message_count=0)]
    with patch("api.routes.conversations.list_for_user", return_value=rows) as listed:
        resp = authed_client.get(
            "/conversations",
            headers={"Authorization": "Bearer user-jwt"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "conversations" in body
    assert len(body["conversations"]) == 2
    assert body["conversations"][0]["summary"] == "About the weather"
    assert body["conversations"][0]["message_count"] == 4
    assert body["conversations"][1]["ended_at"] is None
    listed.assert_called_once()
    args, kwargs = listed.call_args
    assert args[0] == fake_user
    assert kwargs == {"limit": 50, "offset": 0, "supabase_token": "user-jwt"}


def test_list_conversations_returns_empty_list(authed_client: TestClient) -> None:
    with patch("api.routes.conversations.list_for_user", return_value=[]):
        resp = authed_client.get(
            "/conversations",
            headers={"Authorization": "Bearer user-jwt"},
        )
    assert resp.status_code == 200
    assert resp.json() == {"conversations": []}


def test_list_conversations_passes_pagination(authed_client: TestClient) -> None:
    with patch("api.routes.conversations.list_for_user", return_value=[]) as listed:
        resp = authed_client.get(
            "/conversations?limit=10&offset=20",
            headers={"Authorization": "Bearer user-jwt"},
        )
    assert resp.status_code == 200
    _, kwargs = listed.call_args
    assert kwargs["limit"] == 10
    assert kwargs["offset"] == 20


def test_list_conversations_returns_401_without_token(client: TestClient) -> None:
    resp = client.get("/conversations")
    assert resp.status_code == 401
    assert resp.headers.get("WWW-Authenticate") == "Bearer"


def test_get_conversation_returns_full_payload(
    authed_client: TestClient,
    fake_user: User,
) -> None:
    conv_id = uuid4()
    msg_id = uuid4()
    conv = Conversation(
        id=conv_id,
        user_id=fake_user.id,
        started_at=datetime(2026, 5, 4, 12, 0, tzinfo=UTC),
        ended_at=None,
        summary=None,
        metadata={},
        messages=[
            Message(
                id=msg_id,
                conversation_id=conv_id,
                role="user",
                content="hello",
                tool_name=None,
                tool_args=None,
                tool_result=None,
                created_at=datetime(2026, 5, 4, 12, 1, tzinfo=UTC),
            ),
            Message(
                id=uuid4(),
                conversation_id=conv_id,
                role="tool",
                content="",
                tool_name="get_weather",
                tool_args={"city": "Berlin"},
                tool_result={"temp": 20},
                created_at=datetime(2026, 5, 4, 12, 2, tzinfo=UTC),
            ),
        ],
    )
    with patch("api.routes.conversations.get", return_value=conv) as fetched:
        resp = authed_client.get(
            f"/conversations/{conv_id}",
            headers={"Authorization": "Bearer user-jwt"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(conv_id)
    assert len(body["messages"]) == 2
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][0]["content"] == "hello"
    assert body["messages"][1]["tool_name"] == "get_weather"
    fetched.assert_called_once()
    args, kwargs = fetched.call_args
    assert args[0] == fake_user
    assert isinstance(args[1], UUID)
    assert kwargs == {"supabase_token": "user-jwt"}


def test_get_conversation_returns_404_when_missing(authed_client: TestClient) -> None:
    with patch("api.routes.conversations.get", return_value=None):
        resp = authed_client.get(
            f"/conversations/{uuid4()}",
            headers={"Authorization": "Bearer user-jwt"},
        )
    assert resp.status_code == 404
    body = resp.json()
    assert body["detail"]["code"] == "conversation_not_found"


def test_get_conversation_returns_401_without_token(client: TestClient) -> None:
    resp = client.get(f"/conversations/{uuid4()}")
    assert resp.status_code == 401
    assert resp.headers.get("WWW-Authenticate") == "Bearer"
