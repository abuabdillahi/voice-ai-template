"""Session-level integration test for the episodic memory tools.

Acceptance criterion 08's session test reads:

    "Scripts a multi-turn conversation that should trigger `remember`
     then later `recall`; asserts both tools were dispatched."

The LiveKit Agents 1.5.x test harness for end-to-end voice-loop
scripting is still flagged as an evals tool and brittle across patch
releases (see :mod:`test_session_tools`). The existing session tests
follow the same escape hatch the issue brief allows: assert the
*contract* the harness would otherwise verify — that dispatching the
two tools through the same path the LiveKit wrapper uses produces the
expected mem0 calls in the expected order.

This test scripts the contract directly. Turn 1 is "I'm learning
Spanish" — the realtime model would synthesise a `remember` call with
that content. Turn 2, in a later session, is "give me a study tip"
where the agent would call `recall("Spanish")` before answering. We
exercise both dispatches and assert the mem0 client saw the right
arguments in the right order.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
import structlog
from agent.session import _SessionDeps
from core import memory as core_memory
from core.auth import User
from core.tools import dispatch
from core.tools.registry import ToolContext


def _deps() -> _SessionDeps:
    return _SessionDeps(
        user=User(id=UUID("11111111-1111-1111-1111-111111111111"), email="alice@example.com"),
        log=structlog.get_logger("test"),
    )


class _RecordingMem0:
    """Mem0 client double — same shape as the unit test fake, scoped here.

    Defined locally rather than imported so the agent test package
    stays independent of the core test fixtures.
    """

    def __init__(self) -> None:
        self.add_calls: list[tuple[str, dict[str, Any]]] = []
        self.search_calls: list[tuple[str, dict[str, Any]]] = []
        self.search_response: Any = []

    def add(
        self,
        messages: str,
        *,
        user_id: str | None = None,
        filters: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        self.add_calls.append(
            (messages, {"user_id": user_id, "filters": filters, "metadata": metadata})
        )
        return None

    def search(
        self,
        query: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 5,
    ) -> Any:
        self.search_calls.append((query, {"filters": filters, "limit": limit}))
        return self.search_response

    def get_all(
        self,
        *,
        filters: dict[str, Any] | None = None,  # noqa: ARG002
        limit: int = 10,  # noqa: ARG002
    ) -> Any:
        return []


@pytest.mark.asyncio
async def test_remember_then_recall_dispatches_through_mem0() -> None:
    """The two tools forward to mem0 in the order the agent would call them."""
    fake = _RecordingMem0()
    fake.search_response = [{"id": "m1", "memory": "is learning Spanish", "score": 0.9}]
    core_memory.set_client_for_tests(fake)  # type: ignore[arg-type]
    try:
        deps = _deps()
        ctx = ToolContext(
            user=deps.user,
            log=deps.log,
            supabase_access_token="user-jwt",
        )

        # Turn 1 (session 1): the user mentions an incidental fact.
        # The realtime model synthesises a `remember` call.
        confirm = await dispatch(
            "remember",
            {"content": "I'm learning Spanish"},
            ctx,
        )
        assert isinstance(confirm, str)
        assert "remember" in confirm.lower()

        # Turn 2 (session 2): the user asks for a study tip. The agent
        # consults its episodic store via `recall` before answering.
        recalled = await dispatch("recall", {"query": "Spanish"}, ctx)
        assert isinstance(recalled, str)
        assert "Spanish" in recalled

        # Both mem0 calls landed with the right arguments. mem0 ≥2.0
        # routes the per-user scope through `filters`; we also pass
        # `user_id` for backward compat across versions.
        assert fake.add_calls == [
            (
                "I'm learning Spanish",
                {
                    "user_id": str(deps.user.id),
                    "filters": {"user_id": str(deps.user.id)},
                    "metadata": None,
                },
            ),
        ]
        assert fake.search_calls == [
            ("Spanish", {"filters": {"user_id": str(deps.user.id)}, "limit": 5}),
        ]
    finally:
        core_memory.set_client_for_tests(None)


@pytest.mark.asyncio
async def test_remember_without_access_token_returns_graceful_message() -> None:
    """When the session lacks a Supabase JWT, the tool degrades gracefully.

    Same contract as the preferences tools: the realtime model receives
    a verbalisable message rather than the session crashing.
    """
    deps = _deps()
    ctx = ToolContext(user=deps.user, log=deps.log, supabase_access_token=None)
    result = await dispatch("remember", {"content": "anything"}, ctx)
    assert isinstance(result, str)
    assert "credentials" in result.lower() or "sign" in result.lower()


@pytest.mark.asyncio
async def test_recall_returns_no_recall_message_when_mem0_finds_nothing() -> None:
    """An empty mem0 result surfaces as a polite verbalisable message."""
    fake = _RecordingMem0()
    fake.search_response = []
    core_memory.set_client_for_tests(fake)  # type: ignore[arg-type]
    try:
        deps = _deps()
        ctx = ToolContext(
            user=deps.user,
            log=deps.log,
            supabase_access_token="user-jwt",
        )
        result = await dispatch("recall", {"query": "nonexistent topic"}, ctx)
        assert isinstance(result, str)
        # The exact wording is implementation-defined; assert the
        # behaviour ("don't have anything") rather than the literal.
        assert "don't have" in result.lower() or "nothing" in result.lower()
    finally:
        core_memory.set_client_for_tests(None)
