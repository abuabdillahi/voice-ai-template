"""HTTP route handlers.

Each new route is added here (or in a domain-specific submodule
imported from here) so that `app.py` stays focused on application
assembly. Handlers translate HTTP into `core` calls and never contain
business logic.
"""

from __future__ import annotations

from typing import Annotated, Any

from core import preferences
from core.auth import User, get_current_user
from core.config import Settings, get_settings
from core.livekit import issue_token
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

router = APIRouter()


def _bearer_token(authorization: str | None) -> str:
    """Extract the bearer token from the `Authorization` header.

    `get_current_user` already validates the token cryptographically;
    this helper just re-extracts the raw string so we can hand it to
    the Supabase client (which needs the full JWT, not the decoded
    claims). Raises 401 with the same shape as the auth dependency
    when the header is missing or malformed — which can only happen if
    a route forgets to pair this with `get_current_user` (callers
    always pair them).
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
    return token


class HealthResponse(BaseModel):
    """Liveness probe payload."""

    status: str


class MeResponse(BaseModel):
    """Authenticated user, projected for the wire."""

    id: str
    email: str


class LivekitTokenRequest(BaseModel):
    """Optional body for `/livekit/token`.

    The room is optional — when omitted, the API picks the per-user
    default (``user-{userId}``). Letting the client name a room is
    useful for tests and for future multi-room features but is not
    required by the demo.
    """

    room: str | None = Field(
        default=None,
        description="Optional LiveKit room name; defaults to `user-{userId}`.",
    )


class LivekitTokenResponse(BaseModel):
    """Connection bundle returned to the browser."""

    token: str = Field(description="Short-lived LiveKit access JWT.")
    url: str = Field(description="LiveKit server URL the browser should dial.")
    room: str = Field(description="Room name encoded in the token's grants.")


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    """Liveness probe. Returns 200 with a static payload."""
    return HealthResponse(status="ok")


@router.get("/me", response_model=MeResponse, tags=["auth"])
def me(current_user: Annotated[User, Depends(get_current_user)]) -> MeResponse:
    """Return the authenticated user's id and email."""
    return MeResponse(id=str(current_user.id), email=current_user.email)


@router.post("/livekit/token", response_model=LivekitTokenResponse, tags=["voice"])
def livekit_token(
    current_user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    payload: LivekitTokenRequest | None = None,
) -> LivekitTokenResponse:
    """Mint a LiveKit access token for the authenticated user.

    The route is a thin adapter over :func:`core.livekit.issue_token`;
    the token's `identity` is the Supabase user id and the room
    defaults to ``user-{userId}`` when the client does not specify one.
    """
    requested_room = payload.room if payload and payload.room else None
    room = requested_room or f"user-{current_user.id}"
    token = issue_token(current_user, room=room, settings=settings)
    return LivekitTokenResponse(token=token, url=settings.livekit_url, room=room)


class PreferencesResponse(BaseModel):
    """Flat key-value map of the authenticated user's preferences.

    The shape is intentionally a single ``preferences`` field rather
    than the response body itself being a free-form object — FastAPI
    + OpenAPI handle nested objects more reliably than top-level
    ``additionalProperties`` schemas, and the frontend reads
    ``response.preferences`` either way.
    """

    preferences: dict[str, Any] = Field(
        default_factory=dict,
        description="All stored preferences for the authenticated user.",
    )


@router.get("/preferences", response_model=PreferencesResponse, tags=["preferences"])
def list_preferences(
    current_user: Annotated[User, Depends(get_current_user)],
    authorization: Annotated[str | None, Header()] = None,
) -> PreferencesResponse:
    """Return every stored preference for the authenticated user.

    Thin adapter over :func:`core.preferences.list`. The user's bearer
    token is forwarded to the Supabase client so RLS policies (defined
    in ``0001_user_preferences.sql``) apply to the database query.
    """
    access_token = _bearer_token(authorization)
    rows = preferences.list(current_user, access_token=access_token)
    return PreferencesResponse(preferences=rows)
