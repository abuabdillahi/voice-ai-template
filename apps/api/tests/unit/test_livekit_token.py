"""Tests for the `/livekit/token` route."""

from __future__ import annotations

from core.auth import User
from fastapi.testclient import TestClient


def test_livekit_token_returns_payload_when_authenticated(
    authed_client: TestClient, fake_user: User
) -> None:
    resp = authed_client.post("/livekit/token")
    assert resp.status_code == 200
    body = resp.json()
    # Shape contract: token + url + room.
    assert set(body) == {"token", "url", "room"}
    assert isinstance(body["token"], str) and body["token"]
    assert body["url"] == "wss://test.livekit.cloud"
    assert body["room"] == f"user-{fake_user.id}"


def test_livekit_token_accepts_custom_room(authed_client: TestClient) -> None:
    resp = authed_client.post("/livekit/token", json={"room": "lobby"})
    assert resp.status_code == 200
    assert resp.json()["room"] == "lobby"


def test_livekit_token_returns_401_without_token(client: TestClient) -> None:
    resp = client.post("/livekit/token")
    assert resp.status_code == 401
    assert resp.headers.get("WWW-Authenticate") == "Bearer"


def test_livekit_token_returns_401_for_invalid_token(client: TestClient) -> None:
    resp = client.post("/livekit/token", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401
