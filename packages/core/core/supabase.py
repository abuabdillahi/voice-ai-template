"""Supabase client factory.

`core.supabase` is the single seam through which other `core` modules
acquire a configured Supabase client. Two flavours exist:

* :func:`get_anon_client` — uses the project anon key. Used for
  service-style operations (e.g. token refresh) where no end-user is in
  scope. Currently unused by the application but provided as the
  symmetric counterpart of :func:`get_user_client`.
* :func:`get_user_client` — builds a per-request client whose PostgREST
  calls carry the end-user's access token. **This is the client every
  user-scoped `core` module uses.** Carrying the user's JWT is what
  makes Supabase's RLS policies apply — without it, queries hit the
  table as the anonymous role and silently return empty result sets.

Tests inject a fake client by monkey-patching `_build_user_client`;
production code never imports the underlying SDK directly.
"""

from __future__ import annotations

from typing import Any, Protocol

from core.config import Settings, get_settings
from supabase import Client, create_client


class SupabaseClientProtocol(Protocol):
    """Structural type for the subset of the Supabase client we use.

    The real :class:`supabase.Client` ships with a much larger surface;
    pinning to the methods we actually call keeps tests free of
    has-to-mock-everything ceremony and lets `mypy --strict` validate
    call sites against a contract that is stable across SDK versions.
    """

    def table(self, table_name: str) -> Any: ...


def _build_user_client(
    *,
    url: str,
    publishable_key: str,
    access_token: str,
) -> Client:
    """Construct a Supabase client whose REST calls carry ``access_token``.

    Carved out so tests can monkey-patch this single seam to substitute
    a fake client without dragging in the network-dependent
    :func:`supabase.create_client`.
    """
    client = create_client(url, publishable_key)
    # PostgREST inspects the Authorization header to determine the
    # database role and `auth.uid()`. Setting the session here propagates
    # the user's JWT into every subsequent `.table(...)` call on this
    # client instance. We pass the access token for both halves of the
    # session because PostgREST only needs the access token; the
    # postgrest-py SDK requires a refresh token argument but we never
    # use it (the API never refreshes — the browser does).
    client.postgrest.auth(access_token)
    return client


def get_user_client(
    access_token: str,
    *,
    settings: Settings | None = None,
) -> Client:
    """Return a Supabase client scoped to the end-user's JWT.

    The returned client's PostgREST calls run as the authenticated user,
    so RLS policies (``auth.uid() = user_id``) apply automatically. Call
    sites in `core.conversations` build one of these per request rather
    than reusing a long-lived global — the overhead is small and the
    alternative is to plumb tokens through every layer.
    """
    settings = settings or get_settings()
    return _build_user_client(
        url=settings.supabase_url,
        publishable_key=settings.supabase_publishable_key,
        access_token=access_token,
    )


def get_anon_client(*, settings: Settings | None = None) -> Client:
    """Return an anon-keyed Supabase client (no end-user context).

    Reserved for service-style operations. RLS denies anything
    user-scoped on this client, which is the correct default.
    """
    settings = settings or get_settings()
    return create_client(settings.supabase_url, settings.supabase_publishable_key)


__all__ = [
    "SupabaseClientProtocol",
    "get_anon_client",
    "get_user_client",
]
