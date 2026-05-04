"""Structured user preferences.

Per-user, per-key preferences persisted in `public.user_preferences`.
Designed for deterministic facts the user states explicitly ("my
favorite color is blue", "call me Alice", "respond in German"). The
episodic / semantic memory layer is separate (see issue 08 + `core.memory`)
and handles less structured recall.

All three call sites (set/get/list) require a Supabase access token so
that PostgREST runs the query as the authenticated user, which is what
makes the table's RLS policies apply. Without the token the query would
hit the table as the `anon` role and silently return no rows. Carrying
the token through the call signature rather than implicitly via a
context-var keeps the contract obvious to call-site readers.
"""

from __future__ import annotations

import builtins
from typing import Any, cast

from core.auth import User
from core.supabase import get_user_client

# `list` is shadowed below by the public `list(user)` API. We bind the
# built-in to a private alias up here so the cast() targets inside
# `get` and `list` keep resolving to the type rather than the local
# function.
_list = builtins.list

_TABLE = "user_preferences"


def set(  # noqa: A001 - intentional shadowing; this is the public API name.
    user: User,
    key: str,
    value: Any,
    *,
    access_token: str,
) -> None:
    """Upsert a preference for ``user``.

    ``value`` is any JSON-serialisable Python value (str, int, dict,
    list, None). It is stored in a `jsonb` column so callers can later
    read structured values back unchanged.

    Idempotent on `(user_id, key)` — calling twice with the same key
    overwrites the previous value and refreshes ``updated_at`` (the
    refresh comes from the `set_updated_at` trigger declared in the
    migration).
    """
    client = get_user_client(access_token)
    payload = {
        "user_id": str(user.id),
        "key": key,
        "value": value,
    }
    # `on_conflict` makes this an UPSERT against the composite primary
    # key. PostgREST returns the inserted/updated row; we ignore it
    # because the API tier doesn't need the round-trip data.
    client.table(_TABLE).upsert(payload, on_conflict="user_id,key").execute()


def get(
    user: User,
    key: str,
    *,
    access_token: str,
) -> Any | None:
    """Return the stored value for ``key``, or ``None`` if not set.

    The RLS policy means a row that does not belong to ``user`` is
    indistinguishable from a row that does not exist — both surface as
    ``None`` here. That is the correct behaviour: leakage of
    "this key exists but is not yours" would itself be a privacy bug.
    """
    client = get_user_client(access_token)
    response = (
        client.table(_TABLE)
        .select("value")
        .eq("user_id", str(user.id))
        .eq("key", key)
        .limit(1)
        .execute()
    )
    # PostgREST returns rows as a list of dicts; the SDK's typing is
    # loose (a JSON union) so we cast to the shape we actually expect.
    # If the table contract changes the cast will lie — but the unit
    # test against the real shape catches that.
    rows = cast(_list[dict[str, Any]], response.data or [])
    if not rows:
        return None
    return rows[0].get("value")


def list(  # noqa: A001 - intentional shadowing; this is the public API name.
    user: User,
    *,
    access_token: str,
) -> dict[str, Any]:
    """Return every preference for ``user`` as a flat ``{key: value}`` dict.

    Order is not guaranteed (PostgREST does not impose one without an
    explicit ``order``); the frontend sorts as needed. RLS limits the
    rows to those owned by ``user`` regardless of any client-side
    filter.
    """
    client = get_user_client(access_token)
    response = client.table(_TABLE).select("key,value").eq("user_id", str(user.id)).execute()
    rows = cast(_list[dict[str, Any]], response.data or [])
    return {str(row["key"]): row["value"] for row in rows}


__all__ = ["get", "list", "set"]
