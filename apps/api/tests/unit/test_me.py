"""Tests for the `/me` route, exercising the auth dependency wiring."""

from __future__ import annotations

from core.auth import User
from fastapi.testclient import TestClient


def test_me_returns_user_when_authenticated(authed_client: TestClient, fake_user: User) -> None:
    resp = authed_client.get("/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"id": str(fake_user.id), "email": fake_user.email}


def test_me_returns_401_without_token(client: TestClient) -> None:
    resp = client.get("/me")
    assert resp.status_code == 401
    assert resp.headers.get("WWW-Authenticate") == "Bearer"


def test_me_returns_401_for_invalid_token(client: TestClient) -> None:
    resp = client.get("/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401


def test_me_returns_401_for_non_bearer_scheme(client: TestClient) -> None:
    resp = client.get("/me", headers={"Authorization": "Basic abc"})
    assert resp.status_code == 401
