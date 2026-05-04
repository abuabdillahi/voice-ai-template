"""LiveKit access-token issuance.

The API exposes a thin `/livekit/token` route that mints short-lived
JWTs the browser hands to LiveKit when joining a room. The signing
logic lives here so a future bridge (CLI, telephony adapter) can mint
tokens without going through HTTP.

Tokens carry the LiveKit "video grants" scoped to a single room. The
identity is the Supabase user id — LiveKit treats this as the
participant key, so the same user reconnecting from another tab will
collide unless the application chooses different room names. For the
template, the convention is one room per user (``user-{userId}``)
which is fine for the demo.

When ``supabase_access_token`` is provided, it is JSON-encoded into
the LiveKit token's ``metadata`` claim under
``{"supabase_access_token": "<jwt>"}``. The agent worker reads this
metadata at session start and forwards the token to RLS-scoped
``core`` operations so per-user database writes succeed.

Security note: LiveKit metadata is visible to the participant client
that holds the LiveKit token. That is acceptable here because the
same client already holds the Supabase JWT in its session storage —
embedding it in the LiveKit token does not widen its exposure.
Downstream apps with stricter requirements (e.g. shared/spectator
participants) should pass the token via a server-side relay instead.
"""

from __future__ import annotations

import json
from datetime import timedelta

from livekit.api import AccessToken, VideoGrants

from core.auth import User
from core.config import Settings, get_settings

DEFAULT_TOKEN_TTL_SECONDS = 15 * 60


def issue_token(
    user: User,
    room: str,
    *,
    ttl_seconds: int = DEFAULT_TOKEN_TTL_SECONDS,
    supabase_access_token: str | None = None,
    settings: Settings | None = None,
) -> str:
    """Mint a LiveKit access token for ``user`` to join ``room``.

    The token grants room join, publish, and subscribe — the minimum
    set required for two-way audio between the user and the agent.
    Identity is the Supabase user id (string form); display name is
    the user's email so the LiveKit dashboard is readable.
    """
    settings = settings or get_settings()

    grants = VideoGrants(
        room_join=True,
        room=room,
        can_publish=True,
        can_subscribe=True,
        can_publish_data=True,
    )

    builder = (
        AccessToken(
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
        )
        .with_identity(str(user.id))
        .with_name(user.email)
        .with_grants(grants)
        .with_ttl(timedelta(seconds=ttl_seconds))
    )

    if supabase_access_token:
        builder = builder.with_metadata(
            json.dumps({"supabase_access_token": supabase_access_token})
        )

    return builder.to_jwt()


__all__ = ["DEFAULT_TOKEN_TTL_SECONDS", "issue_token"]
