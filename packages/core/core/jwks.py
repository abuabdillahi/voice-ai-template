"""JWKS fetching and caching for Supabase JWT verification.

Supabase moved off the legacy HS256 shared-secret scheme in 2026 in favour
of asymmetric JWT Signing Keys (ES256 by default). The verifier no longer
holds the secret used to sign tokens — only the public keys, fetched from
the project's JWKS endpoint at boot and cached for the configured TTL.

This module exposes a single function, :func:`get_jwks`, plus an
:func:`invalidate_jwks` escape hatch that the verifier calls when a
token's ``kid`` claim does not match any cached key (a strong signal that
Supabase rotated keys since the last fetch).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

DEFAULT_TTL_SECONDS = 600
"""How long a cached JWKS document is reused before re-fetching."""

_FETCH_TIMEOUT_SECONDS = 5.0


@dataclass(slots=True)
class _CacheEntry:
    keys: dict[str, Any]
    fetched_at: float


_cache: _CacheEntry | None = None


def get_jwks(url: str, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> dict[str, Any]:
    """Return the JWKS document at ``url``, fetching once per ``ttl_seconds``.

    The cache is process-global. Tests and rare key-rotation paths can
    force a refetch via :func:`invalidate_jwks`.
    """
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache.fetched_at < ttl_seconds:
        return _cache.keys

    with httpx.Client(timeout=_FETCH_TIMEOUT_SECONDS) as client:
        response = client.get(url)
    response.raise_for_status()
    keys: dict[str, Any] = response.json()

    _cache = _CacheEntry(keys=keys, fetched_at=now)
    return keys


def invalidate_jwks() -> None:
    """Drop the cache so the next :func:`get_jwks` re-fetches.

    Called by the verifier when a token references a ``kid`` that is not
    present in the cached document — strong signal that the project
    rotated signing keys.
    """
    global _cache
    _cache = None


__all__ = ["DEFAULT_TTL_SECONDS", "get_jwks", "invalidate_jwks"]
