"""Episodic memory backed by mem0.

`core.memory` is the seam through which the agent and the API write to
and read from the episodic memory store. Where :mod:`core.preferences`
holds deterministic facts keyed by name (favorite color, preferred
language), this module holds incidental facts mentioned in passing
("I'm learning Spanish", "my daughter's name is Maya"). Mem0 owns the
deduplication and conflict-resolution logic; this module is a thin
adapter that constrains the surface to the three calls the rest of the
codebase needs.

The mem0 client is lazy-initialised from :func:`core.config.get_settings`
the first time a function in this module is called. Tests inject a
fake by calling :func:`set_client_for_tests`; production code never
constructs the underlying mem0 ``Memory`` directly.

Like the other persistence modules, every call accepts an optional
``supabase_token``. Mem0 connects to Postgres at the database (not
PostgREST) layer, so it cannot route through Supabase RLS the way
``core.preferences`` does. Instead, mem0 writes the user id into the
memory's payload and the migration's RLS policies (see
``0003_mem0_memories.sql``) filter on ``payload->>'user_id'``. The
Supabase token argument is accepted for symmetry with the other
modules and reserved for a future enhancement that switches mem0 to a
token-aware connection — today it is unused.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, cast

from core.auth import User
from core.config import Settings, get_settings


@dataclass(frozen=True, slots=True)
class Memory:
    """A single recalled memory.

    Mirrors the subset of mem0's ``MemoryItem`` shape we surface to
    callers. ``content`` is the natural-language fact mem0 extracted;
    ``score`` is the similarity score on search results (None for
    listings); ``id`` is mem0's stable identifier so callers can
    correlate updates.
    """

    id: str
    content: str
    score: float | None = None
    metadata: dict[str, Any] | None = None


class MemoryClientProtocol(Protocol):
    """Structural type for the slice of mem0's ``Memory`` we use.

    Pinning to the methods we actually call keeps the unit-test fakes
    small and lets ``mypy --strict`` validate the call sites against a
    contract that is stable across mem0 versions.
    """

    def add(
        self,
        messages: str,
        *,
        user_id: str | None = ...,
        filters: dict[str, Any] | None = ...,
        metadata: dict[str, Any] | None = ...,
    ) -> Any: ...

    def search(
        self,
        query: str,
        *,
        filters: dict[str, Any] | None = ...,
        limit: int = ...,
    ) -> Any: ...

    def get_all(
        self,
        *,
        filters: dict[str, Any] | None = ...,
        limit: int = ...,
    ) -> Any: ...


# Module-level cache of the lazily-built client. Reset by tests via
# :func:`set_client_for_tests`. Held as a module-level singleton rather
# than a class instance because mem0's `Memory` is itself a thread-safe
# container that wraps a connection pool — building a fresh one per
# request would be wasteful.
_CLIENT: MemoryClientProtocol | None = None


def _build_client(settings: Settings) -> MemoryClientProtocol:
    """Construct the real mem0 client from typed settings.

    Imported lazily so the unit-test path that injects a fake never
    pays the mem0 import cost (mem0 transitively imports tiktoken,
    which is heavy).
    """
    # Importing inside the function keeps the test-time mock path light
    # and avoids the ~/.mem0 directory creation mem0 does at import time
    # in environments where the user's home directory is unwritable.
    from mem0 import Memory as Mem0Memory

    config: dict[str, Any] = {
        # Pin the fact-extraction LLM. mem0's default in current
        # releases routes through OpenAI's `max_tokens` parameter, which
        # gpt-5 / o-series models reject with:
        #     'max_tokens' is not supported with this model.
        #     Use 'max_completion_tokens' instead.
        # Pinning to gpt-4o-mini keeps extraction fast, cheap, and on
        # the legacy completion API mem0 currently expects.
        "llm": {
            "provider": "openai",
            "config": {
                "model": "gpt-4o-mini",
                "api_key": settings.openai_api_key,
            },
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "model": "text-embedding-3-small",
                "api_key": settings.openai_api_key,
            },
        },
        "vector_store": {
            "provider": "pgvector",
            "config": {
                "collection_name": settings.mem0_collection,
                "embedding_model_dims": settings.mem0_embedding_dims,
                "connection_string": settings.mem0_postgres_url,
                # The migration in `0003_mem0_memories.sql` already
                # creates the HNSW index, but mem0's create_col path is
                # idempotent so we leave this on for parity with the
                # documented config and for test environments where the
                # migration is not yet applied.
                "hnsw": True,
            },
        },
    }
    return cast(MemoryClientProtocol, Mem0Memory.from_config(config))


def _get_client(settings: Settings | None = None) -> MemoryClientProtocol:
    """Return the lazily-initialised mem0 client."""
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = _build_client(settings or get_settings())
    return _CLIENT


def set_client_for_tests(client: MemoryClientProtocol | None) -> None:
    """Override the mem0 client. Test-only escape hatch.

    Passing ``None`` clears the override so the next call rebuilds from
    settings — used in test teardowns to avoid bleed across tests.
    """
    global _CLIENT
    _CLIENT = client


def _coerce_results(payload: Any) -> list[dict[str, Any]]:
    """Normalise mem0's response shape into a list of dicts.

    Mem0's API has changed between minor versions: ``add``, ``search``,
    and ``get_all`` may return a list of dicts directly, or a dict like
    ``{"results": [...]}``. We accept both so the adapter survives
    upstream churn.
    """
    if payload is None:
        return []
    if isinstance(payload, dict):
        results = payload.get("results")
        if isinstance(results, list):
            return [r for r in results if isinstance(r, dict)]
        return []
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    return []


def _row_to_memory(row: dict[str, Any]) -> Memory:
    """Project mem0's row shape onto the public :class:`Memory` dataclass."""
    raw_id = row.get("id")
    content = row.get("memory") or row.get("content") or ""
    score = row.get("score")
    metadata = row.get("metadata")
    return Memory(
        id=str(raw_id) if raw_id is not None else "",
        content=str(content),
        score=float(score) if isinstance(score, (int, float)) else None,
        metadata=cast(dict[str, Any] | None, metadata) if isinstance(metadata, dict) else None,
    )


def remember(
    user: User,
    content: str,
    *,
    supabase_token: str | None = None,  # noqa: ARG001 — reserved for future RLS-aware client.
) -> None:
    """Persist an incidental fact about ``user`` via mem0.

    Mem0's ``add`` runs a fact-extraction LLM over the text, may merge
    it into an existing memory, and writes the result to pgvector.
    The function returns ``None`` because the agent's tool wrapper
    cares only about success/failure — the structured result mem0
    returns is not surfaced today (a later iteration could expose the
    list of created/updated memory ids if a UI surface needed them).
    """
    client = _get_client()
    # mem0's `add` keeps the top-level `user_id` kwarg as the entity
    # scope — only `get_all`/`search` moved scoping into `filters`.
    client.add(content, user_id=str(user.id))


def recall(
    user: User,
    query: str,
    *,
    limit: int = 5,
    supabase_token: str | None = None,  # noqa: ARG001 — reserved for future RLS-aware client.
) -> list[Memory]:
    """Return ``limit`` memories most similar to ``query`` for ``user``.

    Wraps :meth:`mem0.Memory.search`. The user-scoped filter is applied
    by mem0 itself (it embeds the filter into the SQL ``WHERE`` clause
    on ``payload->>'user_id'``); the RLS policies in the migration are
    a defence-in-depth backstop in case a misconfigured caller forgets
    to pass ``user_id``.
    """
    client = _get_client()
    raw = client.search(query, filters={"user_id": str(user.id)}, limit=limit)
    return [_row_to_memory(row) for row in _coerce_results(raw)]


def list_recent(
    user: User,
    *,
    limit: int = 10,
    supabase_token: str | None = None,  # noqa: ARG001 — reserved for future RLS-aware client.
) -> list[Memory]:
    """Return ``user``'s most recently added memories.

    Used by the "Recent memories" section of the talk-page sidebar.
    Mem0's ``get_all`` does not document an ordering guarantee — the
    underlying pgvector table is ordered by insertion id (a UUID), so
    the slice mem0 returns is "the most recent ``limit``" only by
    convention. The sidebar copy says "recent" rather than "latest"
    to keep the contract honest.
    """
    client = _get_client()
    raw = client.get_all(filters={"user_id": str(user.id)}, limit=limit)
    return [_row_to_memory(row) for row in _coerce_results(raw)]


__all__ = [
    "Memory",
    "MemoryClientProtocol",
    "list_recent",
    "recall",
    "remember",
    "set_client_for_tests",
]
