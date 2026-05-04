"""HTTP route handlers.

Each new route is added here (or in a domain-specific submodule
imported from here) so that `app.py` stays focused on application
assembly. Handlers translate HTTP into `core` calls and never contain
business logic.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from core import conversations, preferences
from core import memory as core_memory
from core.auth import User, get_current_user
from core.config import Settings, get_settings
from core.livekit import issue_token
from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, status
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


class PreferenceUpsertRequest(BaseModel):
    """Body for ``PUT /preferences/{key}``.

    A single ``value`` field rather than free-form JSON so the OpenAPI
    schema (and thus the generated TS types) carries an explicit shape
    the frontend can typecheck. The field is ``Any``-typed to allow
    the existing structured-preferences contract (string today,
    structured values later); validation against the recognised key
    catalogue happens server-side via
    :func:`core.preferences.validate_preference`.
    """

    value: Any = Field(description="New value for the preference.")


class PreferenceUpsertResponse(BaseModel):
    """Echo of the stored value after a ``PUT`` succeeds."""

    key: str
    value: Any


@router.put(
    "/preferences/{key}",
    response_model=PreferenceUpsertResponse,
    tags=["preferences"],
)
def upsert_preference(
    current_user: Annotated[User, Depends(get_current_user)],
    key: Annotated[str, Path(description="Preference key, e.g. 'preferred_name' or 'voice'.")],
    payload: PreferenceUpsertRequest,
    authorization: Annotated[str | None, Header()] = None,
) -> PreferenceUpsertResponse:
    """Upsert a single preference for the authenticated user.

    Validated against :func:`core.preferences.validate_preference`,
    which today only accepts the settings-page keys
    (:data:`core.preferences.SETTINGS_KEYS`). The free-form
    ``set_preference`` agent tool remains available for keys outside
    that catalogue — the settings page is intentionally narrower than
    the agent's surface.

    Returns 400 with a structured error body on validation failure,
    401 without authentication, 200 on success.
    """
    access_token = _bearer_token(authorization)
    try:
        normalised = preferences.validate_preference(key, payload.value)
    except preferences.PreferenceValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_preference", "message": str(exc)},
        ) from exc
    preferences.set(current_user, key, normalised, access_token=access_token)
    return PreferenceUpsertResponse(key=key, value=normalised)


# ---------------------------------------------------------------------------
# Issue 08 — episodic memory routes.
# ---------------------------------------------------------------------------


class MemoryItem(BaseModel):
    """One recalled memory, projected for the wire.

    Mirrors :class:`core.memory.Memory`. We expose ``id`` so a future
    UI can attribute updates back to the same memory; ``score`` is
    intentionally omitted from the listing endpoint because the
    sidebar lists rather than ranks.
    """

    id: str = Field(description="Stable identifier mem0 assigns to the memory.")
    content: str = Field(description="The remembered fact, in natural language.")


class MemoriesResponse(BaseModel):
    """Response payload for ``GET /memories/recent``."""

    memories: list[MemoryItem] = Field(
        default_factory=list,
        description=(
            "The authenticated user's most recent memories, newest-first by mem0's ordering."
        ),
    )


@router.get("/memories/recent", response_model=MemoriesResponse, tags=["memories"])
def list_recent_memories(
    current_user: Annotated[User, Depends(get_current_user)],
    authorization: Annotated[str | None, Header()] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> MemoriesResponse:
    """Return the authenticated user's recent episodic memories.

    Thin adapter over :func:`core.memory.list_recent`. The user's
    bearer token is forwarded for symmetry with the preferences route;
    mem0 itself does not consume the Supabase JWT today (it talks to
    Postgres directly), but RLS policies on ``mem0_memories`` enforce
    user isolation at the database level — see ``0003_mem0_memories.sql``.
    """
    access_token = _bearer_token(authorization)
    rows = core_memory.list_recent(
        current_user,
        limit=limit,
        supabase_token=access_token,
    )
    return MemoriesResponse(
        memories=[MemoryItem(id=m.id, content=m.content) for m in rows],
    )


# ---------------------------------------------------------------------------
# Issue 09 — conversation history routes.
# ---------------------------------------------------------------------------


class ConversationSummaryItem(BaseModel):
    """One row in the history list view.

    Mirrors :class:`core.conversations.ConversationSummary`. We project
    explicitly through pydantic instead of returning the dataclass so
    the OpenAPI schema (and thus the generated TypeScript types) carry
    field-level descriptions.
    """

    id: str = Field(description="Conversation UUID.")
    started_at: datetime = Field(description="When the conversation began.")
    ended_at: datetime | None = Field(
        default=None,
        description="When the conversation ended, or null if still in progress.",
    )
    summary: str | None = Field(
        default=None,
        description="LLM-generated one-line gist; null until the conversation ends.",
    )
    message_count: int = Field(description="Number of messages in the conversation.")


class ConversationsListResponse(BaseModel):
    """Paginated response for ``GET /conversations``."""

    conversations: list[ConversationSummaryItem] = Field(
        default_factory=list,
        description="Conversations ordered by started_at descending.",
    )


class MessageItem(BaseModel):
    """A single transcript turn for the detail view."""

    id: str
    role: str = Field(description="One of 'user', 'assistant', 'tool'.")
    content: str
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_result: Any | None = None
    created_at: datetime


class ConversationDetailResponse(BaseModel):
    """Response payload for ``GET /conversations/{id}``."""

    id: str
    started_at: datetime
    ended_at: datetime | None = None
    summary: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    messages: list[MessageItem] = Field(default_factory=list)


@router.get(
    "/conversations",
    response_model=ConversationsListResponse,
    tags=["conversations"],
)
def list_conversations(
    current_user: Annotated[User, Depends(get_current_user)],
    authorization: Annotated[str | None, Header()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ConversationsListResponse:
    """Return the authenticated user's conversations, paginated.

    Thin adapter over :func:`core.conversations.list_for_user`. RLS
    enforces user scoping at the database; the route just shapes the
    response. ``limit`` is bounded server-side so a hostile client
    cannot ask for the whole table.
    """
    access_token = _bearer_token(authorization)
    rows = conversations.list_for_user(
        current_user,
        limit=limit,
        offset=offset,
        supabase_token=access_token,
    )
    return ConversationsListResponse(
        conversations=[
            ConversationSummaryItem(
                id=str(s.id),
                started_at=s.started_at,
                ended_at=s.ended_at,
                summary=s.summary,
                message_count=s.message_count,
            )
            for s in rows
        ]
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetailResponse,
    tags=["conversations"],
)
def get_conversation(
    current_user: Annotated[User, Depends(get_current_user)],
    conversation_id: Annotated[UUID, Path(description="Conversation UUID.")],
    authorization: Annotated[str | None, Header()] = None,
) -> ConversationDetailResponse:
    """Return one conversation with its full message log.

    Returns 404 when the conversation does not exist *or* belongs to
    another user. Both surface here as ``None`` from the core layer
    because RLS makes "not yours" indistinguishable from "not there"
    — leaking the difference would itself be a privacy bug.
    """
    access_token = _bearer_token(authorization)
    conv = conversations.get(
        current_user,
        conversation_id,
        supabase_token=access_token,
    )
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "conversation_not_found", "message": "No such conversation."},
        )
    return ConversationDetailResponse(
        id=str(conv.id),
        started_at=conv.started_at,
        ended_at=conv.ended_at,
        summary=conv.summary,
        metadata=conv.metadata,
        messages=[
            MessageItem(
                id=str(m.id),
                role=m.role,
                content=m.content,
                tool_name=m.tool_name,
                tool_args=m.tool_args,
                tool_result=m.tool_result,
                created_at=m.created_at,
            )
            for m in conv.messages
        ],
    )
