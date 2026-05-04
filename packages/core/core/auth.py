"""Supabase JWT verification and the FastAPI current-user dependency.

The `core.auth` module is the only place in the codebase that knows how
Supabase tokens are validated. API route handlers and (later) the agent
worker depend on `get_current_user` and never look at the JWT directly.

Supabase issues HS256 JWTs signed with the project's JWT secret. The
secret is loaded via :mod:`core.config`. Validation checks the signature,
expiry, and the `aud` claim, then extracts the user id (`sub`) and
`email` claim into a typed :class:`User`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from jose import JWTError, jwt

from core.config import Settings, get_settings

# Supabase signs all access tokens with HS256 by default. We pin the
# algorithm rather than accepting whatever the token header asks for —
# accepting "none" or RS256 from a token that was issued under HS256
# would be a classic algorithm-confusion vulnerability.
_ALGORITHM = "HS256"
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


def verify_token(token: str, *, settings: Settings | None = None) -> User:
    """Validate a Supabase JWT and return the :class:`User` it identifies.

    Raises :class:`AuthError` on any failure (bad signature, expired
    token, unexpected algorithm, missing claims). Callers translate that
    to an HTTP 401 — see :func:`get_current_user`.
    """
    settings = settings or get_settings()
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=[_ALGORITHM],
            audience=_AUDIENCE,
            options={"require": ["exp", "sub"]},
        )
    except JWTError as exc:
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
