"""Unit tests for the :mod:`core.safety_events` module surface.

Mirrors the test patterns established in
``tests/unit/test_preferences_module.py`` and
``tests/unit/test_conversations_module.py``: the Supabase client is
monkey-patched at :func:`core.supabase.get_user_client` so the tests
exercise the module's payload shaping and parsing without a real
database. The RLS isolation guarantee is exercised against a real
Postgres in :mod:`tests.integration.test_safety_events_rls`.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from core import safety_events
from core.auth import User


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"inserted": [], "select_filters": [], "rows_to_return": []}

    class _FakeClient:
        def table(self, name: str) -> _FakeClient:
            state["table"] = name
            return self

        def insert(self, payload: dict[str, Any]) -> _FakeClient:
            state["last_payload"] = payload
            state["inserted"].append(payload)
            return self

        def select(self, *_args: Any, **_kwargs: Any) -> _FakeClient:
            return self

        def eq(self, column: str, value: Any) -> _FakeClient:
            state["select_filters"].append((column, value))
            return self

        def order(self, column: str, *, desc: bool) -> _FakeClient:
            state["order"] = (column, desc)
            return self

        def execute(self) -> Any:
            if (
                state["inserted"]
                and "last_payload" in state
                and state["inserted"][-1] is state["last_payload"]
            ):
                # Insert path — return one persisted row.
                row = {
                    "id": str(uuid4()),
                    **state["last_payload"],
                    "created_at": "2026-05-04T00:00:00+00:00",
                }
                state["last_payload"] = None
                return MagicMock(data=[row])
            # Read path — return whatever the test seeded.
            return MagicMock(data=state["rows_to_return"])

    def _factory(_token: str, **_kwargs: Any) -> _FakeClient:
        return _FakeClient()

    monkeypatch.setattr("core.safety_events.get_user_client", _factory)
    return state


def test_record_writes_a_row_with_expected_payload(fake_client: dict[str, Any]) -> None:
    conv_id = UUID("33333333-3333-3333-3333-333333333333")
    user_id = UUID("11111111-1111-1111-1111-111111111111")
    event = safety_events.record(
        conv_id,
        user_id,
        "emergent",
        "regex",
        ["chest_pain"],
        "I am having chest pain right now",
        supabase_token="user-jwt",
    )
    assert fake_client["table"] == "safety_events"
    payload = fake_client["inserted"][0]
    assert payload["conversation_id"] == str(conv_id)
    assert payload["user_id"] == str(user_id)
    assert payload["tier"] == "emergent"
    assert payload["source"] == "regex"
    assert payload["matched_flags"] == ["chest_pain"]
    assert payload["utterance"] == "I am having chest pain right now"
    assert event.tier == "emergent"
    assert event.matched_flags == ["chest_pain"]


def test_list_for_user_orders_by_created_at_descending(fake_client: dict[str, Any]) -> None:
    user = User(id=UUID("11111111-1111-1111-1111-111111111111"), email="alice@example.com")
    fake_client["rows_to_return"] = [
        {
            "id": str(uuid4()),
            "conversation_id": str(uuid4()),
            "user_id": str(user.id),
            "tier": "emergent",
            "source": "regex",
            "matched_flags": ["chest_pain"],
            "utterance": "chest pain",
            "created_at": "2026-05-04T01:00:00+00:00",
        },
        {
            "id": str(uuid4()),
            "conversation_id": str(uuid4()),
            "user_id": str(user.id),
            "tier": "urgent",
            "source": "regex",
            "matched_flags": ["saddle_anaesthesia"],
            "utterance": "numb saddle",
            "created_at": "2026-05-04T00:00:00+00:00",
        },
    ]
    rows = safety_events.list_for_user(user, supabase_token="user-jwt")
    assert fake_client["order"] == ("created_at", True)
    assert fake_client["select_filters"] == [("user_id", str(user.id))]
    assert [r.tier for r in rows] == ["emergent", "urgent"]


def test_record_raises_when_insert_returns_no_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """RLS denial returns no rows — surface that loudly."""

    class _DenyingClient:
        def table(self, _name: str) -> _DenyingClient:
            return self

        def insert(self, _payload: dict[str, Any]) -> _DenyingClient:
            return self

        def execute(self) -> Any:
            return MagicMock(data=[])

    monkeypatch.setattr("core.safety_events.get_user_client", lambda _t, **_k: _DenyingClient())
    with pytest.raises(RuntimeError, match="check RLS"):
        safety_events.record(
            uuid4(),
            uuid4(),
            "emergent",
            "regex",
            [],
            "x",
            supabase_token="user-jwt",
        )
