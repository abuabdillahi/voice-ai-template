"""Unit tests for `core.memory`.

The mem0 client is mocked at the seam :func:`core.memory.set_client_for_tests`
exposes so the tests stay deterministic and offline. They assert the
externally-observable contract of each function: which mem0 method is
called, with which arguments, and how the response shape is unwrapped
into the public :class:`Memory` dataclass.

The integration test in ``tests/integration/test_memory_with_mem0.py``
covers the database round-trip behaviour when feasible.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import pytest
from core import memory as core_memory
from core.auth import User
from core.memory import Memory, MemoryClientProtocol

_USER = User(id=UUID("11111111-1111-1111-1111-111111111111"), email="alice@example.com")


@dataclass(slots=True)
class _FakeMem0:
    """Recording double for the slice of mem0's client we use.

    Captures every invocation so tests can assert which method was
    called with which arguments. Returns whatever pre-canned response
    has been set for the next call.
    """

    add_calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    search_calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    get_all_calls: list[dict[str, Any]] = field(default_factory=list)
    add_response: Any = None
    search_response: Any = field(default_factory=list)
    get_all_response: Any = field(default_factory=list)

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
        return self.add_response

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
        filters: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> Any:
        self.get_all_calls.append({"filters": filters, "limit": limit})
        return self.get_all_response


@pytest.fixture
def fake_client() -> Iterator[_FakeMem0]:
    """Inject a recording mem0 fake; clear it on teardown."""
    client = _FakeMem0()
    # The protocol is structural; the concrete dataclass satisfies it.
    core_memory.set_client_for_tests(client)  # type: ignore[arg-type]
    try:
        yield client
    finally:
        core_memory.set_client_for_tests(None)


def test_remember_calls_mem0_add_with_str_user_id(fake_client: _FakeMem0) -> None:
    core_memory.remember(_USER, "I'm learning Spanish")

    assert len(fake_client.add_calls) == 1
    content, kwargs = fake_client.add_calls[0]
    assert content == "I'm learning Spanish"
    # mem0 ≥2.0 wants the per-user scope inside `filters`. We also pass
    # `user_id` for backward-compat with versions that still wire the
    # top-level kwarg to the JSONB payload.
    assert kwargs["user_id"] == str(_USER.id)
    assert kwargs["filters"] == {"user_id": str(_USER.id)}


def test_recall_returns_list_of_memory_dataclasses(fake_client: _FakeMem0) -> None:
    fake_client.search_response = [
        {"id": "abc", "memory": "is learning Spanish", "score": 0.91},
        {"id": "def", "memory": "has a daughter named Maya", "score": 0.42},
    ]

    results = core_memory.recall(_USER, "languages", limit=3)

    assert results == [
        Memory(id="abc", content="is learning Spanish", score=0.91, metadata=None),
        Memory(id="def", content="has a daughter named Maya", score=0.42, metadata=None),
    ]
    # The query, user-scoped filter, and limit must reach mem0 unchanged.
    assert fake_client.search_calls == [
        ("languages", {"filters": {"user_id": str(_USER.id)}, "limit": 3}),
    ]


def test_recall_handles_results_dict_shape(fake_client: _FakeMem0) -> None:
    # Some mem0 versions wrap results in a `{"results": [...]}` envelope.
    # The adapter coerces both shapes so callers see one contract.
    fake_client.search_response = {
        "results": [
            {"id": "x", "memory": "likes hiking", "score": 0.7},
        ]
    }
    [recalled] = core_memory.recall(_USER, "outdoors")
    assert recalled.content == "likes hiking"
    assert recalled.score == 0.7


def test_recall_returns_empty_list_when_mem0_returns_none(fake_client: _FakeMem0) -> None:
    fake_client.search_response = None
    assert core_memory.recall(_USER, "nothing") == []


def test_list_recent_uses_default_limit_of_ten(fake_client: _FakeMem0) -> None:
    fake_client.get_all_response = [
        {"id": "1", "memory": "first"},
        {"id": "2", "memory": "second"},
    ]
    results = core_memory.list_recent(_USER)
    assert [m.content for m in results] == ["first", "second"]
    # `score` is None for listings (mem0's `get_all` does not score).
    assert all(m.score is None for m in results)
    assert fake_client.get_all_calls == [{"filters": {"user_id": str(_USER.id)}, "limit": 10}]


def test_list_recent_respects_explicit_limit(fake_client: _FakeMem0) -> None:
    fake_client.get_all_response = []
    core_memory.list_recent(_USER, limit=3)
    assert fake_client.get_all_calls == [{"filters": {"user_id": str(_USER.id)}, "limit": 3}]


def test_set_client_for_tests_clears_when_none() -> None:
    """Sanity check: passing ``None`` resets the cache.

    Without this, a test that injects a fake and then forgets to clear
    it would leak into subsequent test modules. The fixture's teardown
    relies on this behaviour.
    """
    sentinel: MemoryClientProtocol = _FakeMem0()  # type: ignore[assignment]
    core_memory.set_client_for_tests(sentinel)
    core_memory.set_client_for_tests(None)
    # After reset, the next call would rebuild from settings — we don't
    # exercise that here because it would hit the real mem0; the
    # observable effect is that the module-level cache is None.
    assert core_memory._CLIENT is None
