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

    def _summary_fn(_msgs: list[Message]) -> tuple[str, str | None]:
        sentinel_called["called"] = True
        return ("should not be used", None)

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

    def _summary_fn(msgs: list[Message]) -> tuple[str, str | None]:
        captured_msgs["msgs"] = msgs
        return ("Discussed the weather.", "Recall: discussed weather forecasts.")

    conversations.end(_CONV_ID, supabase_token=_TOKEN, summary_fn=_summary_fn)

    assert len(captured_msgs["msgs"]) == 3
    updates = [args for n, args, _ in factory.update_calls if n == "update"]
    assert len(updates) == 1
    payload = updates[0][0]
    assert payload["summary"] == "Discussed the weather."
    assert payload["recall_context"] == "Recall: discussed weather forecasts."
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


def _tool_message(
    *,
    tool_name: str,
    tool_args: dict[str, Any] | None,
    tool_result: Any,
    when: datetime | None = None,
) -> Message:
    return Message(
        id=uuid4(),
        conversation_id=_CONV_ID,
        role="tool",
        content="",
        tool_name=tool_name,
        tool_args=tool_args,
        tool_result=tool_result,
        created_at=when or datetime(2026, 5, 4, tzinfo=UTC),
    )


def _user_message(content: str = "hi") -> Message:
    return Message(
        id=uuid4(),
        conversation_id=_CONV_ID,
        role="user",
        content=content,
        tool_name=None,
        tool_args=None,
        tool_result=None,
        created_at=datetime(2026, 5, 4, tzinfo=UTC),
    )


def test_extract_identified_condition_returns_condition_id_for_single_success() -> None:
    msgs = [
        _user_message(),
        _tool_message(
            tool_name="recommend_treatment",
            tool_args={"condition_id": "carpal_tunnel"},
            tool_result={"condition_id": "carpal_tunnel", "name": "Carpal tunnel syndrome"},
        ),
    ]
    assert conversations.extract_identified_condition(msgs) == "carpal_tunnel"


def test_extract_identified_condition_returns_most_recent() -> None:
    msgs = [
        _tool_message(
            tool_name="recommend_treatment",
            tool_args={"condition_id": "lumbar_strain"},
            tool_result={"condition_id": "lumbar_strain"},
        ),
        _user_message(),
        _tool_message(
            tool_name="recommend_treatment",
            tool_args={"condition_id": "tension_type_headache"},
            tool_result={"condition_id": "tension_type_headache"},
        ),
    ]
    assert conversations.extract_identified_condition(msgs) == "tension_type_headache"


def test_extract_identified_condition_skips_error_tool_calls() -> None:
    msgs = [
        _tool_message(
            tool_name="recommend_treatment",
            tool_args={"condition_id": "upper_trapezius_strain"},
            tool_result={"condition_id": "upper_trapezius_strain"},
        ),
        _tool_message(
            tool_name="recommend_treatment",
            tool_args={"condition_id": "carpal_tunnel"},
            tool_result={"error": "below confidence threshold"},
        ),
    ]
    # The most recent successful call is the trapezius one; the error
    # row must not shadow it.
    assert conversations.extract_identified_condition(msgs) == "upper_trapezius_strain"


def test_extract_identified_condition_returns_none_for_unknown_condition() -> None:
    msgs = [
        _tool_message(
            tool_name="recommend_treatment",
            tool_args={"condition_id": "not_a_real_condition"},
            tool_result={"condition_id": "not_a_real_condition"},
        ),
    ]
    assert conversations.extract_identified_condition(msgs) is None


def test_extract_identified_condition_returns_none_when_no_recommend_treatment() -> None:
    msgs = [
        _user_message(),
        _tool_message(
            tool_name="record_symptom",
            tool_args={"slot": "location", "value": "wrist"},
            tool_result={"ok": True},
        ),
    ]
    assert conversations.extract_identified_condition(msgs) is None


class _StubChoice:
    def __init__(self, content: str) -> None:
        self.message = type("_M", (), {"content": content})()


class _StubResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_StubChoice(content)]


class _StubChat:
    def __init__(self, response: Any) -> None:
        self.completions = self
        self._response = response
        self.captured: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> Any:
        self.captured.update(kwargs)
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class _StubOpenAI:
    last: _StubChat | None = None

    def __init__(self, *_a: Any, **_k: Any) -> None:
        self.chat = _StubChat(_StubOpenAI._next_response)  # type: ignore[arg-type]
        _StubOpenAI.last = self.chat

    _next_response: Any = None


def _install_stub_openai(
    monkeypatch: pytest.MonkeyPatch,
    response: Any,
) -> type[_StubOpenAI]:
    import sys
    import types

    fake_module = types.ModuleType("openai")
    _StubOpenAI._next_response = response
    fake_module.OpenAI = _StubOpenAI  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", fake_module)
    return _StubOpenAI


def _settings_for_summary() -> Any:
    from core.config import Settings

    return Settings(
        livekit_api_key="lk-test-key",  # pragma: allowlist secret
        livekit_api_secret="lk-test-secret",  # pragma: allowlist secret
        livekit_url="wss://test.livekit.cloud",
        openai_api_key="sk-test",  # pragma: allowlist secret
        supabase_url="https://test.supabase.co",
        supabase_jwks_url="https://test.supabase.co/auth/v1/.well-known/jwks.json",
        supabase_jwt_secret="test-secret",  # pragma: allowlist secret
        supabase_anon_key="anon-key",  # pragma: allowlist secret
        supabase_service_role_key="service-key",  # pragma: allowlist secret
    )


def test_default_summary_and_recall_fn_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    import json as _json

    payload = _json.dumps(
        {
            "summary": "Discussed wrist tingling.",
            "recall_context": "User reported wrist tingling consistent with carpal tunnel; "
            "agent recommended the carpal tunnel protocol.",
        }
    )
    _install_stub_openai(monkeypatch, _StubResponse(payload))

    msgs = [
        _user_message("my wrist is tingling"),
        _tool_message(
            tool_name="recommend_treatment",
            tool_args={"condition_id": "carpal_tunnel"},
            tool_result={"condition_id": "carpal_tunnel", "name": "Carpal tunnel syndrome"},
        ),
    ]
    summary, recall = conversations._default_summary_and_recall_fn(  # type: ignore[attr-defined]
        msgs, settings=_settings_for_summary()
    )
    assert summary == "Discussed wrist tingling."
    assert recall is not None and "carpal tunnel" in recall.lower()
    captured = _StubOpenAI.last.captured if _StubOpenAI.last else {}
    user_messages = [m for m in captured.get("messages", []) if m.get("role") == "user"]
    # The transcript carries the recommend_treatment call so the LLM
    # can ground the recall blob in what was actually recommended.
    assert any(
        "recommend_treatment" in (m.get("content") or "") for m in user_messages
    ), "recommend_treatment tool message must be in the prompt input"


def test_default_summary_and_recall_fn_malformed_json_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stub_openai(monkeypatch, _StubResponse("not json at all"))
    msgs = [_user_message("hello there friend")]
    summary, recall = conversations._default_summary_and_recall_fn(  # type: ignore[attr-defined]
        msgs, settings=_settings_for_summary()
    )
    assert recall is None
    assert summary  # truncation fallback returns the leading transcript chars
    assert "hello" in summary


def test_default_summary_and_recall_fn_exception_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stub_openai(monkeypatch, RuntimeError("network down"))
    msgs = [_user_message("hello there friend")]
    summary, recall = conversations._default_summary_and_recall_fn(  # type: ignore[attr-defined]
        msgs, settings=_settings_for_summary()
    )
    assert recall is None
    assert summary
    assert "hello" in summary


def test_end_persists_identified_condition_and_recall(monkeypatch: pytest.MonkeyPatch) -> None:
    rec_msg_args = {"condition_id": "tension_type_headache"}
    msgs_data: list[dict[str, Any]] = [
        {
            "id": str(uuid4()),
            "conversation_id": str(_CONV_ID),
            "role": "user",
            "content": "my head hurts",
            "tool_name": None,
            "tool_args": None,
            "tool_result": None,
            "created_at": _NOW_ISO,
        },
        {
            "id": str(uuid4()),
            "conversation_id": str(_CONV_ID),
            "role": "assistant",
            "content": "tell me more",
            "tool_name": None,
            "tool_args": None,
            "tool_result": None,
            "created_at": _NOW_ISO,
        },
        {
            "id": str(uuid4()),
            "conversation_id": str(_CONV_ID),
            "role": "tool",
            "content": "",
            "tool_name": "recommend_treatment",
            "tool_args": rec_msg_args,
            "tool_result": {"condition_id": "tension_type_headache"},
            "created_at": _NOW_ISO,
        },
    ]
    factory = _RoutingClientFactory(messages_data=msgs_data)
    monkeypatch.setattr("core.conversations.get_user_client", factory)

    def _summary_fn(_msgs: list[Message]) -> tuple[str, str | None]:
        return ("Discussed tension headache.", "Recall: discussed tension headache.")

    conversations.end(_CONV_ID, supabase_token=_TOKEN, summary_fn=_summary_fn)

    updates = [args for n, args, _ in factory.update_calls if n == "update"]
    payload = updates[0][0]
    assert payload["summary"] == "Discussed tension headache."
    assert payload["recall_context"] == "Recall: discussed tension headache."
    assert payload["identified_condition_id"] == "tension_type_headache"


def test_list_recent_with_recall_filters_and_orders(monkeypatch: pytest.MonkeyPatch) -> None:
    conv_a, conv_b = uuid4(), uuid4()  # noqa: F841 — fixtures, ids not asserted
    client = _FakeClient(
        data=[
            {
                "started_at": "2026-05-04T12:00:00+00:00",
                "identified_condition_id": "carpal_tunnel",
                "recall_context": "User reported wrist tingling.",
            },
            {
                "started_at": "2026-05-03T12:00:00+00:00",
                "identified_condition_id": "tension_type_headache",
                "recall_context": None,
            },
        ]
    )
    monkeypatch.setattr("core.conversations.get_user_client", lambda *_a, **_k: client)

    sessions = conversations.list_recent_with_recall(_USER, supabase_token=_TOKEN)

    assert [s.identified_condition_id for s in sessions] == [
        "carpal_tunnel",
        "tension_type_headache",
    ]
    assert sessions[0].recall_context == "User reported wrist tingling."
    assert sessions[1].recall_context is None
    eq_calls = _calls_named(client, "eq")
    assert ("user_id", str(_USER.id)) in eq_calls
    filter_calls = _calls_named(client, "filter")
    assert ("identified_condition_id", "not.is", "null") in filter_calls
    order_calls = _calls_named(client, "order")
    assert order_calls and order_calls[0][0] == "started_at"
    limit_calls = _calls_named(client, "limit")
    assert limit_calls and limit_calls[0][0] == 3


def test_list_recent_with_recall_without_token_raises() -> None:
    with pytest.raises(PermissionError):
        conversations.list_recent_with_recall(_USER)


# ---------------------------------------------------------------------------
# has_prior_session — narrow boolean used by the disclaimer-branching path
# ---------------------------------------------------------------------------


def test_has_prior_session_true_when_count_at_least_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """At least one conversation row → returning user, short refresher path."""
    client = _FakeClient(data=[{"id": str(uuid4())}])
    monkeypatch.setattr("core.conversations.get_user_client", lambda *_a, **_k: client)

    assert conversations.has_prior_session(_USER, supabase_token=_TOKEN) is True
    assert client.last_table == "conversations"
    eq_calls = _calls_named(client, "eq")
    assert ("user_id", str(_USER.id)) in eq_calls


def test_has_prior_session_false_when_count_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """No prior rows → first-time user, full disclaimer path."""
    client = _FakeClient(data=[])
    monkeypatch.setattr("core.conversations.get_user_client", lambda *_a, **_k: client)

    assert conversations.has_prior_session(_USER, supabase_token=_TOKEN) is False


def test_has_prior_session_false_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """A transient Supabase error degrades to ``False`` (safe default — full disclaimer plays)."""

    def _boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("network down")

    monkeypatch.setattr("core.conversations.get_user_client", _boom)
    assert conversations.has_prior_session(_USER, supabase_token=_TOKEN) is False


def test_has_prior_session_passes_user_token_to_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Must call ``get_user_client`` with the user's access token, not the service-role key.

    Mirrors the existing ``list_for_user`` / ``list_recent_with_recall``
    token-scoping convention so RLS policies apply.
    """
    received: dict[str, Any] = {}

    def _factory(token: str, **kwargs: Any) -> Any:
        received["token"] = token
        return _FakeClient(data=[])

    monkeypatch.setattr("core.conversations.get_user_client", _factory)
    conversations.has_prior_session(_USER, supabase_token=_TOKEN)
    assert received["token"] == _TOKEN


def test_generate_summary_and_recall_uses_injected_callable() -> None:
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

    def _fn(messages: list[Message]) -> tuple[str, str | None]:
        assert messages == [msg]
        return ("summary text", "recall blob")

    out = conversations.generate_summary_and_recall(_CONV_ID, messages=[msg], summary_fn=_fn)
    assert out == ("summary text", "recall blob")


def test_generate_summary_and_recall_requires_messages() -> None:
    with pytest.raises(ValueError):
        conversations.generate_summary_and_recall(_CONV_ID)
