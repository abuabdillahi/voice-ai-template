"""Supabase JWT verification and the FastAPI current-user dependency.

The `core.auth` module is the only place in the codebase that knows how
Supabase tokens are validated. API route handlers and the agent worker
depend on `get_current_user` and never look at the JWT directly.

Supabase signs access tokens with asymmetric JWT Signing Keys — ES256 by
default, RS256 accepted for forward compatibility. The verifier fetches
the public keys via the project's JWKS endpoint
(``{SUPABASE_URL}/auth/v1/.well-known/jwks.json``), caches them, and
re-fetches when a token references an unknown ``kid`` (key rotation) or
when the cache TTL expires.

The legacy HS256 shared-secret path was removed in issue 13. The
``SUPABASE_JWT_SECRET`` env var is retained as optional for backward
compat with `.env` files cloned before the migration but is no longer
consulted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

import httpx
from fastapi import Depends, Header, HTTPException, status
from jose import JWTError, jwt

from core.config import Settings, get_settings
from core.jwks import get_jwks, invalidate_jwks

# Algorithms the verifier will accept. Pin to asymmetric only — accepting
# HS256 alongside ES256 would re-introduce algorithm-confusion risk.
_ALGORITHMS = ["ES256", "RS256"]
# Supabase's default access-token audience.
_AUDIENCE = "authenticated"


@dataclass(frozen=True, slots=True)
class User:
    """Authenticated end-user, resolved from a verified Supabase JWT.

    Carrying only the fields downstream code needs keeps this type a
    stable contract — additional claims are never silently smuggled
    through.
    """

    id: UUID
    email: str


class AuthError(Exception):
    """Raised by :func:`verify_token` when a token cannot be trusted."""


def _jwks_url(settings: Settings) -> str:
    """Resolve the JWKS endpoint, honouring the optional override."""
    if settings.supabase_jwks_url:
        return settings.supabase_jwks_url
    return f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"


def _decode(token: str, jwks: dict[str, Any]) -> dict[str, Any]:
    return jwt.decode(
        token,
        jwks,
        algorithms=_ALGORITHMS,
        audience=_AUDIENCE,
        options={"require": ["exp", "sub"]},
    )


def verify_token(token: str, *, settings: Settings | None = None) -> User:
    """Validate a Supabase JWT and return the :class:`User` it identifies.

    Raises :class:`AuthError` on any failure (bad signature, expired
    token, unexpected algorithm, missing claims). Callers translate that
    to an HTTP 401 — see :func:`get_current_user`.

    Implements one transparent retry on JWKS lookup failure: if a token's
    ``kid`` does not match any cached public key, the cache is dropped and
    re-fetched once before failing — this absorbs Supabase key rotations
    without operator intervention.
    """
    settings = settings or get_settings()
    url = _jwks_url(settings)

    try:
        jwks = get_jwks(url)
    except httpx.HTTPError as exc:
        raise AuthError(f"unable to fetch JWKS: {exc}") from exc

    try:
        claims: dict[str, Any] = _decode(token, jwks)
    except JWTError:
        # Could be a kid miss after rotation — refresh once and retry.
        invalidate_jwks()
        try:
            jwks = get_jwks(url)
            claims = _decode(token, jwks)
        except (JWTError, httpx.HTTPError) as exc:
            raise AuthError(f"invalid token: {exc}") from exc

    sub = claims.get("sub")
    email = claims.get("email")
    if not isinstance(sub, str) or not sub:
        raise AuthError("token is missing the `sub` claim")
    if not isinstance(email, str) or not email:
        raise AuthError("token is missing the `email` claim")

    try:
        user_id = UUID(sub)
    except ValueError as exc:
        raise AuthError(f"`sub` claim is not a UUID: {sub!r}") from exc

    return User(id=user_id, email=email)


SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_current_user(
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """FastAPI dependency that resolves the bearer token to a :class:`User`.

    On any failure the endpoint returns 401 with a structured detail.
    The detail intentionally avoids leaking which specific check failed
    so that a probe cannot distinguish "no such user" from "expired
    token".
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "missing_authorization",
                "message": "Authorization header is required.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "invalid_authorization_scheme",
                "message": "Authorization header must use the Bearer scheme.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        return verify_token(token, settings=settings)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_token", "message": str(exc)},
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


__all__ = ["AuthError", "User", "get_current_user", "verify_token"]
