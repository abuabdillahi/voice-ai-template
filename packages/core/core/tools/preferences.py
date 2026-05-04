"""Preference get/set tools exposed to the agent.

These two tools are the agent's window into the structured preferences
table. Together with the system-prompt nudge ("when the user states a
preference, call set_preference"), they realise the cross-session
memory promise from the PRD: a user states a fact, signs out, signs
back in, and the assistant still knows it.

The implementations are intentionally small — they're thin adapters
over :mod:`core.preferences`. The interesting design choice is the
input shape: the registry's schema-derivation only supports primitive
parameters today (issue 06's note), so ``value`` is typed as ``str``.
Richer values (lists, dicts) would require either extending the
registry or a domain-specific JSON-encoded variant; both are deferred
until a real downstream tool needs them.
"""

from __future__ import annotations

from core import preferences
from core.tools.registry import ToolContext, tool

# Surfaced as a module-level constant so handlers and tests reference
# the same string. Kept short so the realtime model can verbalise it
# naturally if the agent has to apologise.
_NO_AUTH_MSG = (
    "I can't save preferences in this session because I don't have "
    "your account credentials handy. Please try again after signing in."
)


@tool
async def set_preference(ctx: ToolContext, key: str, value: str) -> str:
    """Save a stated preference for the current user.

    Use this whenever the user states a preference about themselves —
    favorite color, preferred name, preferred language, dietary
    constraints, and so on. ``key`` should be a short snake_case
    identifier (e.g. ``favorite_color``, ``preferred_name``); ``value``
    is the literal value the user said.
    """
    if ctx.supabase_access_token is None:
        ctx.log.warning("set_preference.no_access_token")
        return _NO_AUTH_MSG
    preferences.set(
        ctx.user,
        key,
        value,
        access_token=ctx.supabase_access_token,
    )
    return f"Saved {key}: {value}."


@tool
async def get_preference(ctx: ToolContext, key: str) -> str:
    """Look up a previously-saved preference for the current user.

    Use this before answering personal questions ("what's my favorite
    colour?", "what name should I use for you?") so the response uses
    what the user has actually told you. Returns ``"no preference set"``
    when no value is stored — say so naturally rather than fabricating.
    """
    if ctx.supabase_access_token is None:
        ctx.log.warning("get_preference.no_access_token")
        return _NO_AUTH_MSG
    value = preferences.get(
        ctx.user,
        key,
        access_token=ctx.supabase_access_token,
    )
    if value is None:
        return "no preference set"
    # `value` is jsonb — strings come back as Python strings; structured
    # values come back as dicts/lists. The realtime model can verbalise
    # either, but we coerce to a string here so the tool's contract
    # matches the registry's "string return" shape.
    return value if isinstance(value, str) else str(value)


__all__ = ["get_preference", "set_preference"]
