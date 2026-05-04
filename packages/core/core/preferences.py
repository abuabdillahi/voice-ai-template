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


# ---------------------------------------------------------------------------
# Recognised-key catalogue.
# ---------------------------------------------------------------------------
# Two write paths reach this table. The validated path —
# ``PUT /preferences/{key}`` — runs values through
# ``validate_preference`` so an unknown key or an out-of-list value is
# rejected at the API edge rather than silently stored. The agent's
# free-form path through ``core.tools.preferences.set_preference`` is
# deliberately unvalidated, so the agent can save arbitrary
# user-stated facts (favourite_color, dietary_restrictions, anything
# else) without us having to extend this catalogue first.

#: OpenAI Realtime voice ids the assistant can speak in. Sourced from
#: the OpenAI Realtime API documentation.
OPENAI_REALTIME_VOICES: tuple[str, ...] = (
    "alloy",
    "ash",
    "ballad",
    "coral",
    "echo",
    "sage",
    "shimmer",
    "verse",
)

#: Settings-page key for the user's preferred display / spoken name.
PREFERRED_NAME_KEY = "preferred_name"

#: Settings-page key for the OpenAI Realtime voice the assistant uses.
VOICE_KEY = "voice"

#: Settings-page keys, in display order. Used by the ``PUT
#: /preferences/{key}`` endpoint to validate the route parameter.
SETTINGS_KEYS: tuple[str, ...] = (PREFERRED_NAME_KEY, VOICE_KEY)


class PreferenceValidationError(ValueError):
    """Raised when ``validate_preference`` rejects a key or value.

    A ``ValueError`` subclass so existing handlers that catch
    ``ValueError`` keep working; a distinct type so the API layer can
    map it to a 400 without swallowing other ``ValueError``s.
    """


def validate_preference(key: str, value: Any) -> Any:
    """Validate a settings-page preference write.

    Returns the (possibly normalised) value on success; raises
    :class:`PreferenceValidationError` otherwise. The function is the
    single source of truth used by both the ``PUT /preferences/{key}``
    handler and the agent worker's session-start read (defensively
    re-validating values stored before this function existed).

    Rules:

    * ``preferred_name`` — non-empty string, trimmed; capped at 80
      chars so a malicious / accidental novel does not blow up the
      system prompt.
    * ``voice`` — must be a member of :data:`OPENAI_REALTIME_VOICES`.
    * Any other ``key`` — rejected. The settings UI is intentionally
      narrow; the agent's free-form ``set_preference`` tool covers the
      open-ended case via :mod:`core.preferences`.
    """
    if key == PREFERRED_NAME_KEY:
        if not isinstance(value, str):
            raise PreferenceValidationError(f"{PREFERRED_NAME_KEY!r} must be a string.")
        trimmed = value.strip()
        if not trimmed:
            raise PreferenceValidationError(f"{PREFERRED_NAME_KEY!r} must not be empty.")
        if len(trimmed) > 80:
            raise PreferenceValidationError(
                f"{PREFERRED_NAME_KEY!r} must be 80 characters or fewer."
            )
        return trimmed
    if key == VOICE_KEY:
        if not isinstance(value, str) or value not in OPENAI_REALTIME_VOICES:
            raise PreferenceValidationError(
                f"{VOICE_KEY!r} must be one of: {', '.join(OPENAI_REALTIME_VOICES)}."
            )
        return value
    raise PreferenceValidationError(f"Unknown settings key: {key!r}.")


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


__all__ = [
    "OPENAI_REALTIME_VOICES",
    "PREFERRED_NAME_KEY",
    "PreferenceValidationError",
    "SETTINGS_KEYS",
    "VOICE_KEY",
    "get",
    "list",
    "set",
    "validate_preference",
]
