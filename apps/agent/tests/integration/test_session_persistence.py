"""Session-level test for the issue 09 conversation-persistence hooks.

Mirrors the contract-shaped test pattern established by
:mod:`test_session_preferences`: rather than spin up a full LiveKit
WebRTC harness (still flagged as evals-tier and brittle across patch
releases), assert the persistence path the hooks would fire by driving
:func:`core.conversations.append_message` directly with payloads
shaped exactly like the ones the LiveKit ``ConversationItemAdded`` and
``FunctionToolsExecuted`` events would produce. Together with the
session-tools test (which proves the LiveKit wiring) and the unit /
integration tests on `core.conversations`, this proves the persistence
chain is wired end-to-end without instantiating a real session.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
import structlog
from agent.session import (
    _persist_tool_message,
    _resolve_supabase_token,
)
from core import conversations as core_conversations


def _now_iso() -> str:
    return "2026-05-04T00:00:00+00:00"


@pytest.fixture
def captured_inserts(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture every payload that lands at the messages table."""
    captured: list[dict[str, Any]] = []
    msg_id_seq = iter(uuid4() for _ in range(100))

    class _RecordingClient:
        def table(self, name: str) -> Any:
            self._table = name
            return self

        def insert(self, payload: dict[str, Any]) -> Any:
            captured.append({"table": self._table, "payload": payload})
            self._last_payload = payload
            return self

        def execute(self) -> Any:
            mid = next(msg_id_seq)
            data = [
                {
                    "id": str(mid),
                    "conversation_id": self._last_payload.get("conversation_id", ""),
                    "role": self._last_payload.get("role", "user"),
                    "content": self._last_payload.get("content", ""),
                    "tool_name": self._last_payload.get("tool_name"),
                    "tool_args": self._last_payload.get("tool_args"),
                    "tool_result": self._last_payload.get("tool_result"),
                    "created_at": _now_iso(),
                }
            ]
            return MagicMock(data=data)

    def _factory(_token: str, **_kwargs: Any) -> _RecordingClient:
        return _RecordingClient()

    monkeypatch.setattr("core.conversations.get_user_client", _factory)
    return captured


def test_user_turn_appends_user_role_message(
    captured_inserts: list[dict[str, Any]],
) -> None:
    conv_id = UUID("33333333-3333-3333-3333-333333333333")
    core_conversations.append_message(
        conv_id, "user", "what is the weather in Berlin?", supabase_token="user-jwt"
    )
    assert len(captured_inserts) == 1
    payload = captured_inserts[0]["payload"]
    assert captured_inserts[0]["table"] == "messages"
    assert payload["role"] == "user"
    assert payload["content"] == "what is the weather in Berlin?"
    assert payload["conversation_id"] == str(conv_id)


def test_assistant_turn_appends_assistant_role_message(
    captured_inserts: list[dict[str, Any]],
) -> None:
    conv_id = UUID("33333333-3333-3333-3333-333333333333")
    core_conversations.append_message(
        conv_id, "assistant", "It's 20 degrees in Berlin.", supabase_token="user-jwt"
    )
    assert captured_inserts[0]["payload"]["role"] == "assistant"
    assert captured_inserts[0]["payload"]["content"] == "It's 20 degrees in Berlin."


def test_tool_call_persistence_helper_writes_tool_row(
    captured_inserts: list[dict[str, Any]],
) -> None:
    log = structlog.get_logger("test")
    conv_id = UUID("33333333-3333-3333-3333-333333333333")
    _persist_tool_message(
        conv_id=conv_id,
        supabase_token="user-jwt",
        log=log,
        tool_name="get_weather",
        tool_args={"city": "Berlin"},
        tool_result="It's 20 degrees in Berlin.",
    )
    assert len(captured_inserts) == 1
    payload = captured_inserts[0]["payload"]
    assert payload["role"] == "tool"
    assert payload["content"] == ""
    assert payload["tool_name"] == "get_weather"
    assert payload["tool_args"] == {"city": "Berlin"}
    assert payload["tool_result"] == "It's 20 degrees in Berlin."


def test_tool_call_persistence_helper_skips_when_no_token(
    captured_inserts: list[dict[str, Any]],
) -> None:
    log = structlog.get_logger("test")
    _persist_tool_message(
        conv_id=UUID("33333333-3333-3333-3333-333333333333"),
        supabase_token=None,
        log=log,
        tool_name="get_weather",
        tool_args={},
        tool_result=None,
    )
    assert captured_inserts == []


def test_tool_call_persistence_helper_swallows_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = structlog.get_logger("test")

    def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("postgrest unreachable")

    monkeypatch.setattr("core.conversations.append_message", _boom)
    # Must not raise — best-effort persistence.
    _persist_tool_message(
        conv_id=UUID("33333333-3333-3333-3333-333333333333"),
        supabase_token="user-jwt",
        log=log,
        tool_name="get_weather",
        tool_args={},
        tool_result=None,
    )


def test_resolve_supabase_token_returns_none_for_empty_metadata() -> None:
    """Without participant metadata, the helper returns None."""

    class _Claims:
        identity = "11111111-1111-1111-1111-111111111111"
        name = "alice@example.com"
        metadata = ""

    class _Ctx:
        def token_claims(self) -> Any:
            return _Claims()

    assert _resolve_supabase_token(_Ctx()) is None  # type: ignore[arg-type]


def test_resolve_supabase_token_extracts_value_from_json_metadata() -> None:
    import json as _json

    class _Claims:
        identity = "11111111-1111-1111-1111-111111111111"
        name = "alice@example.com"
        metadata = _json.dumps({"supabase_access_token": "user-jwt"})

    class _Ctx:
        def token_claims(self) -> Any:
            return _Claims()

    assert _resolve_supabase_token(_Ctx()) == "user-jwt"  # type: ignore[arg-type]
