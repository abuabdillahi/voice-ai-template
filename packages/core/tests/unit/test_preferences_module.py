"""Unit tests for `core.preferences`.

The Supabase client is mocked at :func:`core.supabase.get_user_client`
so the tests stay deterministic and offline. They assert the
externally-observable contract of each function: which table is
queried, which filters are applied, and how the response shape is
unwrapped.

The integration test in ``tests/integration/test_preferences_rls.py``
covers the RLS behaviour against a real Postgres.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from core import preferences
from core.auth import User

_USER = User(id=UUID("11111111-1111-1111-1111-111111111111"), email="alice@example.com")
_TOKEN = "user-jwt"


class _FakeQuery:
    """Recording double for the chained PostgREST builder.

    Captures every method call + args and returns ``self`` so the
    chain remains fluent. ``execute()`` returns whatever ``data`` was
    pre-set on the parent fake client.
    """

    def __init__(self, sink: list[tuple[str, tuple[Any, ...], dict[str, Any]]], data: Any) -> None:
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

    def table(self, name: str) -> _FakeQuery:
        self.last_table = name
        return _FakeQuery(self.calls, self.data)


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> _FakeClient:
    """Patch :func:`core.supabase.get_user_client` to return a fake."""
    client = _FakeClient()

    def _factory(token: str, **_kwargs: Any) -> _FakeClient:
        # Capture the token so tests can assert it propagated correctly.
        client.calls.append(("__token__", (token,), {}))
        return client

    monkeypatch.setattr("core.preferences.get_user_client", _factory)
    return client


def _patch_client_factory(
    monkeypatch: pytest.MonkeyPatch,
    client: _FakeClient,
) -> None:
    """Helper used by the per-test factories."""

    def _factory(_token: str, **_kwargs: Any) -> _FakeClient:
        return client

    monkeypatch.setattr("core.preferences.get_user_client", _factory)


def _calls_named(client: _FakeClient, name: str) -> list[tuple[Any, ...]]:
    return [args for n, args, _ in client.calls if n == name]


def test_set_upserts_with_user_id_key_value(fake_client: _FakeClient) -> None:
    preferences.set(_USER, "favorite_color", "blue", access_token=_TOKEN)

    assert fake_client.last_table == "user_preferences"
    upserts = _calls_named(fake_client, "upsert")
    assert len(upserts) == 1
    payload = upserts[0][0]
    assert payload == {
        "user_id": str(_USER.id),
        "key": "favorite_color",
        "value": "blue",
    }
    # Upsert must specify the composite-key conflict target so the
    # table's PRIMARY KEY (user_id, key) drives the merge.
    upsert_kwargs = [kw for n, _, kw in fake_client.calls if n == "upsert"][0]
    assert upsert_kwargs == {"on_conflict": "user_id,key"}
    # The token is passed to the client factory unchanged.
    assert _calls_named(fake_client, "__token__") == [(_TOKEN,)]


def test_set_accepts_arbitrary_json_value(fake_client: _FakeClient) -> None:
    payload_value: dict[str, Any] = {"primary": "blue", "accent": ["red", "yellow"]}
    preferences.set(_USER, "palette", payload_value, access_token=_TOKEN)
    upserts = _calls_named(fake_client, "upsert")
    assert upserts[0][0]["value"] == payload_value


def test_get_returns_value_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(data=[{"value": "blue"}])
    _patch_client_factory(monkeypatch, client)
    result = preferences.get(_USER, "favorite_color", access_token=_TOKEN)
    assert result == "blue"
    assert client.last_table == "user_preferences"
    # The query filters on user_id AND key — RLS does the user side too,
    # but explicit filtering keeps the query plan tight.
    eq_calls = _calls_named(client, "eq")
    assert ("user_id", str(_USER.id)) in eq_calls
    assert ("key", "favorite_color") in eq_calls


def test_get_returns_none_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(data=[])
    _patch_client_factory(monkeypatch, client)
    assert preferences.get(_USER, "missing", access_token=_TOKEN) is None


def test_get_returns_structured_value(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(data=[{"value": {"a": 1, "b": [2, 3]}}])
    _patch_client_factory(monkeypatch, client)
    assert preferences.get(_USER, "k", access_token=_TOKEN) == {"a": 1, "b": [2, 3]}


def test_list_returns_flat_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(
        data=[
            {"key": "favorite_color", "value": "blue"},
            {"key": "preferred_name", "value": "Alice"},
        ]
    )
    _patch_client_factory(monkeypatch, client)
    result = preferences.list(_USER, access_token=_TOKEN)
    assert result == {"favorite_color": "blue", "preferred_name": "Alice"}


def test_list_returns_empty_dict_when_no_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(data=[])
    _patch_client_factory(monkeypatch, client)
    assert preferences.list(_USER, access_token=_TOKEN) == {}


# ---------------------------------------------------------------------------
# Issue 10 — validate_preference
# ---------------------------------------------------------------------------


def test_validate_preferred_name_strips_and_returns() -> None:
    assert preferences.validate_preference("preferred_name", "  Sam  ") == "Sam"


def test_validate_preferred_name_rejects_empty() -> None:
    with pytest.raises(preferences.PreferenceValidationError):
        preferences.validate_preference("preferred_name", "")
    with pytest.raises(preferences.PreferenceValidationError):
        preferences.validate_preference("preferred_name", "   ")


def test_validate_preferred_name_rejects_non_string() -> None:
    with pytest.raises(preferences.PreferenceValidationError):
        preferences.validate_preference("preferred_name", 42)


def test_validate_preferred_name_caps_length() -> None:
    long = "x" * 81
    with pytest.raises(preferences.PreferenceValidationError):
        preferences.validate_preference("preferred_name", long)


def test_validate_voice_accepts_listed_value() -> None:
    for voice in preferences.OPENAI_REALTIME_VOICES:
        assert preferences.validate_preference("voice", voice) == voice


def test_validate_voice_rejects_unlisted_value() -> None:
    with pytest.raises(preferences.PreferenceValidationError):
        preferences.validate_preference("voice", "fake-voice")


def test_validate_rejects_unknown_key() -> None:
    with pytest.raises(preferences.PreferenceValidationError):
        preferences.validate_preference("favorite_color", "blue")
