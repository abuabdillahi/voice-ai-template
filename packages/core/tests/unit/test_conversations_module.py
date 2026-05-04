"""Unit tests for `core.conversations`.

The Supabase client is mocked at :func:`core.supabase.get_user_client`
so the tests stay deterministic and offline. They assert the
externally-observable contract of each function: which table is
queried, which filters are applied, and how the response shape is
unwrapped.

The integration test in ``tests/integration/test_conversations_rls.py``
covers the RLS behaviour against a real Postgres.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from core import conversations
from core.auth import User
from core.conversations import Message

_USER = User(id=UUID("11111111-1111-1111-1111-111111111111"), email="alice@example.com")
_TOKEN = "user-jwt"
_CONV_ID = UUID("22222222-2222-2222-2222-222222222222")
_NOW_ISO = "2026-05-04T00:00:00+00:00"


class _FakeQuery:
    """Recording double for the chained PostgREST builder."""

    def __init__(
        self,
        sink: list[tuple[str, tuple[Any, ...], dict[str, Any]]],
        data: Any,
    ) -> None:
        self._sink = sink
        self._data = data

    def __getattr__(self, name: str) -> Any:
        def _record(*args: Any, **kwargs: Any) -> Any:
            self._sink.append((name, args, kwargs))
            return self

        return _record

    def execute(self) -> Any:
        self._sink.append(("execute", (), {}))
        return MagicMock(data=self._data)


class _FakeClient:
    def __init__(self, data: Any = None) -> None:
        self.data = data
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.last_table: str | None = None
        self.tables_seen: list[str] = []

    def table(self, name: str) -> _FakeQuery:
        self.last_table = name
        self.tables_seen.append(name)
        return _FakeQuery(self.calls, self.data)


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> _FakeClient:
    client = _FakeClient()

    def _factory(_token: str, **_kwargs: Any) -> _FakeClient:
        return client

    monkeypatch.setattr("core.conversations.get_user_client", _factory)
    return client


def _calls_named(client: _FakeClient, name: str) -> list[tuple[Any, ...]]:
    return [args for n, args, _ in client.calls if n == name]


def test_start_inserts_and_returns_uuid(monkeypatch: pytest.MonkeyPatch) -> None:
    new_id = uuid4()
    client = _FakeClient(data=[{"id": str(new_id)}])
    monkeypatch.setattr("core.conversations.get_user_client", lambda *_a, **_k: client)

    result = conversations.start(_USER, supabase_token=_TOKEN)

    assert result == new_id
    assert client.last_table == "conversations"
    inserts = _calls_named(client, "insert")
    assert len(inserts) == 1
    payload = inserts[0][0]
    assert payload == {"user_id": str(_USER.id)}


def test_start_without_token_raises() -> None:
    with pytest.raises(PermissionError):
        conversations.start(_USER)


def test_append_message_user_role_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    msg_id = uuid4()
    client = _FakeClient(
        data=[
            {
                "id": str(msg_id),
                "conversation_id": str(_CONV_ID),
                "role": "user",
                "content": "hello",
                "tool_name": None,
                "tool_args": None,
                "tool_result": None,
                "created_at": _NOW_ISO,
            }
        ]
    )
    monkeypatch.setattr("core.conversations.get_user_client", lambda *_a, **_k: client)

    msg = conversations.append_message(_CONV_ID, "user", "hello", supabase_token=_TOKEN)

    assert msg.role == "user"
    assert msg.content == "hello"
    assert msg.id == msg_id
    assert client.last_table == "messages"
    payload = _calls_named(client, "insert")[0][0]
    assert payload["conversation_id"] == str(_CONV_ID)
    assert payload["role"] == "user"
    assert payload["content"] == "hello"
    assert "tool_name" not in payload  # only included when supplied


def test_append_message_tool_role_carries_structured_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    msg_id = uuid4()
    client = _FakeClient(
        data=[
            {
                "id": str(msg_id),
                "conversation_id": str(_CONV_ID),
                "role": "tool",
                "content": "",
                "tool_name": "get_weather",
                "tool_args": {"city": "Berlin"},
                "tool_result": {"temp": 20},
                "created_at": _NOW_ISO,
            }
        ]
    )
    monkeypatch.setattr("core.conversations.get_user_client", lambda *_a, **_k: client)

    msg = conversations.append_message(
        _CONV_ID,
        "tool",
        "",
        tool_name="get_weather",
        tool_args={"city": "Berlin"},
        tool_result={"temp": 20},
        supabase_token=_TOKEN,
    )

    assert msg.tool_name == "get_weather"
    assert msg.tool_args == {"city": "Berlin"}
    assert msg.tool_result == {"temp": 20}
    payload = _calls_named(client, "insert")[0][0]
    assert payload["tool_name"] == "get_weather"
    assert payload["tool_args"] == {"city": "Berlin"}
    assert payload["tool_result"] == {"temp": 20}


def test_append_message_rejects_invalid_role() -> None:
    with pytest.raises(ValueError):
        conversations.append_message(
            _CONV_ID,
            "system",  # not in the CHECK constraint
            "nope",
            supabase_token=_TOKEN,
        )


class _RoutingClientFactory:
    """Returns clients shaped per-table.

    `core.conversations.end` calls `get_user_client` more than once
    (one for the update, one for the inner messages SELECT). Returning
    a fresh client per call but routing data by `table()` keeps each
    test scenario assertable in isolation.
    """

    def __init__(self, *, messages_data: list[dict[str, Any]]) -> None:
        self.messages_data = messages_data
        self.update_calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.update_table: str | None = None

    def __call__(self, _token: str, **_kwargs: Any) -> Any:
        outer = self

        class _Client:
            def table(self, name: str) -> Any:
                outer.update_table = name
                if name == "messages":
                    return _FakeQuery([], outer.messages_data)
                return _FakeQuery(outer.update_calls, [])

        return _Client()


def test_end_without_summary_below_threshold_skips_summarisation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # _list_messages returns two rows — below the 3-message threshold,
    # so no summariser is invoked and `summary` stays NULL on the
    # update payload.
    messages_data: list[dict[str, Any]] = [
        {
            "id": str(uuid4()),
            "conversation_id": str(_CONV_ID),
            "role": "user",
            "content": "hi",
            "tool_name": None,
            "tool_args": None,
            "tool_result": None,
            "created_at": _NOW_ISO,
        },
        {
            "id": str(uuid4()),
            "conversation_id": str(_CONV_ID),
            "role": "assistant",
            "content": "hello",
            "tool_name": None,
            "tool_args": None,
            "tool_result": None,
            "created_at": _NOW_ISO,
        },
    ]
    factory = _RoutingClientFactory(messages_data=messages_data)
    monkeypatch.setattr("core.conversations.get_user_client", factory)

    sentinel_called: dict[str, bool] = {"called": False}

    def _summary_fn(_msgs: list[Message]) -> str:
        sentinel_called["called"] = True
        return "should not be used"

    conversations.end(_CONV_ID, supabase_token=_TOKEN, summary_fn=_summary_fn)

    assert sentinel_called["called"] is False
    updates = [args for n, args, _ in factory.update_calls if n == "update"]
    assert len(updates) == 1
    payload = updates[0][0]
    assert "ended_at" in payload
    # No summary on the payload because the threshold was not met.
    assert "summary" not in payload


def test_end_calls_summary_fn_when_threshold_met(monkeypatch: pytest.MonkeyPatch) -> None:
    msgs_data = [
        {
            "id": str(uuid4()),
            "conversation_id": str(_CONV_ID),
            "role": "user",
            "content": "hi",
            "tool_name": None,
            "tool_args": None,
            "tool_result": None,
            "created_at": _NOW_ISO,
        },
        {
            "id": str(uuid4()),
            "conversation_id": str(_CONV_ID),
            "role": "assistant",
            "content": "hello there",
            "tool_name": None,
            "tool_args": None,
            "tool_result": None,
            "created_at": _NOW_ISO,
        },
        {
            "id": str(uuid4()),
            "conversation_id": str(_CONV_ID),
            "role": "user",
            "content": "what's the weather?",
            "tool_name": None,
            "tool_args": None,
            "tool_result": None,
            "created_at": _NOW_ISO,
        },
    ]
    factory = _RoutingClientFactory(messages_data=msgs_data)
    monkeypatch.setattr("core.conversations.get_user_client", factory)

    captured_msgs: dict[str, list[Message]] = {}

    def _summary_fn(msgs: list[Message]) -> str:
        captured_msgs["msgs"] = msgs
        return "Discussed the weather."

    conversations.end(_CONV_ID, supabase_token=_TOKEN, summary_fn=_summary_fn)

    assert len(captured_msgs["msgs"]) == 3
    updates = [args for n, args, _ in factory.update_calls if n == "update"]
    assert len(updates) == 1
    payload = updates[0][0]
    assert payload["summary"] == "Discussed the weather."
    assert "ended_at" in payload


def test_end_with_explicit_summary_skips_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    write = _FakeClient(data=[])

    monkeypatch.setattr("core.conversations.get_user_client", lambda *_a, **_k: write)

    conversations.end(
        _CONV_ID,
        summary="Brief chat.",
        supabase_token=_TOKEN,
    )

    payload = _calls_named(write, "update")[0][0]
    assert payload["summary"] == "Brief chat."
    # No SELECT was issued — the same fake client was used and the only
    # mutating method called against it should be `update`.
    assert "select" not in {n for n, _, _ in write.calls}


def test_list_for_user_returns_summaries(monkeypatch: pytest.MonkeyPatch) -> None:
    conv_a, conv_b = uuid4(), uuid4()
    client = _FakeClient(
        data=[
            {
                "id": str(conv_a),
                "started_at": "2026-05-04T12:00:00+00:00",
                "ended_at": "2026-05-04T12:05:00+00:00",
                "summary": "About the weather",
                "messages": [{"count": 4}],
            },
            {
                "id": str(conv_b),
                "started_at": "2026-05-03T12:00:00+00:00",
                "ended_at": None,
                "summary": None,
                "messages": [{"count": 0}],
            },
        ]
    )
    monkeypatch.setattr("core.conversations.get_user_client", lambda *_a, **_k: client)

    summaries = conversations.list_for_user(_USER, supabase_token=_TOKEN)

    assert [s.id for s in summaries] == [conv_a, conv_b]
    assert summaries[0].message_count == 4
    assert summaries[0].summary == "About the weather"
    assert summaries[1].ended_at is None
    assert summaries[1].summary is None
    eq_calls = _calls_named(client, "eq")
    assert ("user_id", str(_USER.id)) in eq_calls


def test_list_for_user_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(data=[])
    monkeypatch.setattr("core.conversations.get_user_client", lambda *_a, **_k: client)
    assert conversations.list_for_user(_USER, supabase_token=_TOKEN) == []


def test_get_returns_full_conversation(monkeypatch: pytest.MonkeyPatch) -> None:
    msg_id = uuid4()

    class _Fake:
        def __init__(self) -> None:
            self.idx = 0

        def __call__(self, _token: str, **_kwargs: Any) -> _FakeClient:
            self.idx += 1
            if self.idx == 1:
                return _FakeClient(
                    data=[
                        {
                            "id": str(_CONV_ID),
                            "user_id": str(_USER.id),
                            "started_at": _NOW_ISO,
                            "ended_at": None,
                            "summary": None,
                            "metadata": {},
                        }
                    ]
                )
            return _FakeClient(
                data=[
                    {
                        "id": str(msg_id),
                        "conversation_id": str(_CONV_ID),
                        "role": "user",
                        "content": "hi",
                        "tool_name": None,
                        "tool_args": None,
                        "tool_result": None,
                        "created_at": _NOW_ISO,
                    }
                ]
            )

    monkeypatch.setattr("core.conversations.get_user_client", _Fake())

    conv = conversations.get(_USER, _CONV_ID, supabase_token=_TOKEN)
    assert conv is not None
    assert conv.id == _CONV_ID
    assert len(conv.messages) == 1
    assert conv.messages[0].id == msg_id
    assert conv.messages[0].content == "hi"


def test_get_returns_none_when_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(data=[])
    monkeypatch.setattr("core.conversations.get_user_client", lambda *_a, **_k: client)
    assert conversations.get(_USER, _CONV_ID, supabase_token=_TOKEN) is None


def test_generate_summary_uses_injected_callable() -> None:
    msg = Message(
        id=uuid4(),
        conversation_id=_CONV_ID,
        role="user",
        content="hello",
        tool_name=None,
        tool_args=None,
        tool_result=None,
        created_at=datetime(2026, 5, 4, tzinfo=UTC),
    )

    def _fn(messages: list[Message]) -> str:
        assert messages == [msg]
        return "summary text"

    out = conversations.generate_summary(_CONV_ID, messages=[msg], summary_fn=_fn)
    assert out == "summary text"


def test_generate_summary_requires_messages() -> None:
    with pytest.raises(ValueError):
        conversations.generate_summary(_CONV_ID)
