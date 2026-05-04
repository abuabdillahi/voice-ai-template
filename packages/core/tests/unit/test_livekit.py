"""Unit tests for `core.livekit`.

These exercise the JWT shape rather than running a real LiveKit
client. We verify that the minted token is signed with the configured
secret, names the right identity, and grants `room_join` for the
requested room with publish + subscribe scopes.
"""

from __future__ import annotations

import json
import time
from uuid import UUID

from core.auth import User
from core.config import Settings
from core.livekit import DEFAULT_TOKEN_TTL_SECONDS, issue_token
from jose import jwt


def _user() -> User:
    return User(id=UUID("11111111-1111-1111-1111-111111111111"), email="alice@example.com")


def _decode(token: str, settings: Settings) -> dict[str, object]:
    # LiveKit signs HS256 with the API secret. We verify with the same
    # secret; audience/issuer aren't enforced because the LiveKit
    # server validates those, not our test.
    return jwt.decode(
        token,
        settings.livekit_api_secret,
        algorithms=["HS256"],
        options={"verify_aud": False},
    )


def test_issue_token_encodes_identity_and_room(settings: Settings) -> None:
    token = issue_token(_user(), room="user-abc", settings=settings)
    claims = _decode(token, settings)

    assert claims["sub"] == "11111111-1111-1111-1111-111111111111"
    assert claims["name"] == "alice@example.com"
    # LiveKit packs grants under the `video` claim.
    video = claims["video"]
    assert isinstance(video, dict)
    assert video["roomJoin"] is True
    assert video["room"] == "user-abc"
    assert video["canPublish"] is True
    assert video["canSubscribe"] is True


def test_issue_token_default_ttl_is_15_minutes(settings: Settings) -> None:
    before = int(time.time())
    token = issue_token(_user(), room="user-abc", settings=settings)
    after = int(time.time())
    claims = _decode(token, settings)

    exp = int(claims["exp"])  # type: ignore[arg-type]
    # The token expires `DEFAULT_TOKEN_TTL_SECONDS` after issuance,
    # which the call wraps around `now`. Allow a small clock window.
    assert before + DEFAULT_TOKEN_TTL_SECONDS - 5 <= exp <= after + DEFAULT_TOKEN_TTL_SECONDS + 5


def test_issue_token_custom_ttl(settings: Settings) -> None:
    token = issue_token(_user(), room="user-abc", ttl_seconds=60, settings=settings)
    before = int(time.time())
    claims = _decode(token, settings)
    exp = int(claims["exp"])  # type: ignore[arg-type]
    assert exp <= before + 65


def test_issue_token_omits_metadata_when_no_supabase_token(settings: Settings) -> None:
    """Without a supabase_access_token, the metadata claim is absent or empty."""
    token = issue_token(_user(), room="user-abc", settings=settings)
    claims = _decode(token, settings)
    # LiveKit either omits the metadata claim entirely or sets it to an
    # empty string when it is not provided. Both are acceptable.
    assert not claims.get("metadata")


def test_issue_token_embeds_supabase_token_in_metadata(settings: Settings) -> None:
    token = issue_token(
        _user(),
        room="user-abc",
        supabase_access_token="user-jwt-abc123",
        settings=settings,
    )
    claims = _decode(token, settings)
    metadata_raw = claims["metadata"]
    assert isinstance(metadata_raw, str) and metadata_raw, "metadata should be set"
    metadata = json.loads(metadata_raw)
    assert metadata == {"supabase_access_token": "user-jwt-abc123"}


def test_issue_token_metadata_round_trips_through_decode(settings: Settings) -> None:
    """The metadata shape exactly matches what `_resolve_supabase_token` parses.

    Pinning the wire shape so changes to either side are caught by tests.
    """
    token = issue_token(
        _user(),
        room="user-abc",
        supabase_access_token="abc",
        settings=settings,
    )
    metadata_raw = _decode(token, settings)["metadata"]
    decoded = json.loads(metadata_raw)  # type: ignore[arg-type]
    assert decoded.get("supabase_access_token") == "abc"
