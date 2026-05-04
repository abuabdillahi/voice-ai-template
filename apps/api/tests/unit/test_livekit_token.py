"""Tests for the `/livekit/token` route."""

from __future__ import annotations

import json

from core.auth import User
from fastapi.testclient import TestClient
from jose import jwt


def test_livekit_token_returns_payload_when_authenticated(
    authed_client: TestClient, fake_user: User
) -> None:
    resp = authed_client.post(
        "/livekit/token",
        headers={"Authorization": "Bearer fake-supabase-jwt"},
    )
    assert resp.status_code == 200
    body = resp.json()
    # Shape contract: token + url + room.
    assert set(body) == {"token", "url", "room"}
    assert isinstance(body["token"], str) and body["token"]
    assert body["url"] == "wss://test.livekit.cloud"
    assert body["room"] == f"user-{fake_user.id}"


def test_livekit_token_accepts_custom_room(authed_client: TestClient) -> None:
    resp = authed_client.post(
        "/livekit/token",
        json={"room": "lobby"},
        headers={"Authorization": "Bearer fake-supabase-jwt"},
    )
    assert resp.status_code == 200
    assert resp.json()["room"] == "lobby"


def test_livekit_token_embeds_supabase_token_in_metadata(
    authed_client: TestClient,
) -> None:
    """The minted LiveKit token carries the user's Supabase JWT in metadata.

    This is the contract the agent worker relies on: at session start,
    ``_resolve_supabase_token`` parses the LiveKit token's metadata
    claim as JSON and reads ``supabase_access_token``.
    """
    resp = authed_client.post(
        "/livekit/token",
        headers={"Authorization": "Bearer caller-supabase-jwt"},
    )
    assert resp.status_code == 200
    livekit_jwt = resp.json()["token"]

    # LiveKit signs HS256 with the configured API secret. The fixture
    # uses `lk-test-secret`. We don't enforce aud/iss because the
    # LiveKit server validates those, not our test.
    claims = jwt.decode(
        livekit_jwt,
        "lk-test-secret",
        algorithms=["HS256"],
        options={"verify_aud": False},
    )
    metadata = json.loads(claims["metadata"])
    assert metadata == {"supabase_access_token": "caller-supabase-jwt"}


def test_livekit_token_returns_401_without_token(client: TestClient) -> None:
    resp = client.post("/livekit/token")
    assert resp.status_code == 401
    assert resp.headers.get("WWW-Authenticate") == "Bearer"


def test_livekit_token_returns_401_for_invalid_token(client: TestClient) -> None:
    resp = client.post("/livekit/token", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401
