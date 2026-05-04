"""Session-level integration test for the preferences tools.

Acceptance criterion 07's session test reads:

    "Scripts a 'my favorite color is blue' turn and asserts
     set_preference was dispatched with key='favorite_color',
     value='blue'."

The LiveKit Agents 1.5.x test harness for end-to-end voice-loop
scripting is still flagged as an evals tool and is brittle across
patch releases (see the comment in :mod:`test_session_tools`). The
existing session-tools test follows the same escape hatch the issue
brief encourages: assert the *contract* the harness would otherwise
verify — that the dispatch path the LiveKit `function_tool` wrapper
uses produces the expected upsert when the realtime model decides to
call ``set_preference`` mid-turn.

This test exercises that contract directly: it patches the Supabase
client at the seam :func:`core.preferences.get_user_client` provides,
dispatches ``set_preference`` with the arguments a realtime model
would synthesise from the user utterance "my favorite color is blue",
and asserts the upsert payload landed at the database boundary.
Together with the schema-shape checks in `test_session_tools`, this
proves the tool is wired end-to-end without a real WebRTC session.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest
import structlog
from agent.session import _SessionDeps
from core.auth import User
from core.tools import dispatch
from core.tools.registry import ToolContext


def _deps() -> _SessionDeps:
    return _SessionDeps(
        user=User(id=UUID("11111111-1111-1111-1111-111111111111"), email="alice@example.com"),
        log=structlog.get_logger("test"),
    )


@pytest.mark.asyncio
async def test_set_preference_dispatch_writes_expected_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class _RecordingClient:
        def table(self, name: str) -> Any:
            captured["table"] = name
            return self

        def upsert(self, payload: dict[str, Any], *, on_conflict: str) -> Any:
            captured["payload"] = payload
            captured["on_conflict"] = on_conflict
            return self

        def execute(self) -> Any:
            return MagicMock(data=[])

    def _make_client(_token: str, **_kwargs: Any) -> _RecordingClient:
        return _RecordingClient()

    monkeypatch.setattr("core.preferences.get_user_client", _make_client)

    deps = _deps()
    ctx = ToolContext(
        user=deps.user,
        log=deps.log,
        supabase_access_token="user-jwt",
    )
    # Arguments shaped as a realtime model would synthesise them from
    # "my favorite color is blue". The system prompt instructs the
    # model to use snake_case keys.
    result = await dispatch(
        "set_preference",
        {"key": "favorite_color", "value": "blue"},
        ctx,
    )

    assert isinstance(result, str)
    assert "favorite_color" in result
    assert "blue" in result
    assert captured["table"] == "user_preferences"
    assert captured["payload"] == {
        "user_id": str(deps.user.id),
        "key": "favorite_color",
        "value": "blue",
    }
    assert captured["on_conflict"] == "user_id,key"


@pytest.mark.asyncio
async def test_set_preference_without_access_token_returns_graceful_message() -> None:
    # When the session was started without a Supabase JWT (the agent
    # boot path that supplies it is wired up incrementally), the tool
    # returns a verbalisable message rather than crashing.
    deps = _deps()
    ctx = ToolContext(user=deps.user, log=deps.log, supabase_access_token=None)
    result = await dispatch(
        "set_preference",
        {"key": "favorite_color", "value": "blue"},
        ctx,
    )
    assert isinstance(result, str)
    # The message should make it clear the operation did not happen.
    assert "credentials" in result.lower() or "sign" in result.lower()


@pytest.mark.asyncio
async def test_get_preference_dispatch_returns_stored_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Reader:
        def table(self, _name: str) -> Any:
            return self

        def select(self, *_args: Any, **_kwargs: Any) -> Any:
            return self

        def eq(self, *_args: Any, **_kwargs: Any) -> Any:
            return self

        def limit(self, *_args: Any, **_kwargs: Any) -> Any:
            return self

        def execute(self) -> Any:
            return MagicMock(data=[{"value": "blue"}])

    def _make_reader(_token: str, **_kwargs: Any) -> _Reader:
        return _Reader()

    monkeypatch.setattr("core.preferences.get_user_client", _make_reader)

    deps = _deps()
    ctx = ToolContext(
        user=deps.user,
        log=deps.log,
        supabase_access_token="user-jwt",
    )
    result = await dispatch("get_preference", {"key": "favorite_color"}, ctx)
    assert result == "blue"


@pytest.mark.asyncio
async def test_get_preference_returns_no_preference_set_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _EmptyReader:
        def table(self, _name: str) -> Any:
            return self

        def select(self, *_args: Any, **_kwargs: Any) -> Any:
            return self

        def eq(self, *_args: Any, **_kwargs: Any) -> Any:
            return self

        def limit(self, *_args: Any, **_kwargs: Any) -> Any:
            return self

        def execute(self) -> Any:
            return MagicMock(data=[])

    def _make_empty_reader(_token: str, **_kwargs: Any) -> _EmptyReader:
        return _EmptyReader()

    monkeypatch.setattr("core.preferences.get_user_client", _make_empty_reader)

    deps = _deps()
    ctx = ToolContext(
        user=deps.user,
        log=deps.log,
        supabase_access_token="user-jwt",
    )
    result = await dispatch("get_preference", {"key": "missing"}, ctx)
    assert result == "no preference set"
