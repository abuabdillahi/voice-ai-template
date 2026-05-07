"""Tests for the `/sessions/prior-status` route."""

from __future__ import annotations

from unittest.mock import patch

from core.auth import User
from fastapi.testclient import TestClient


def test_prior_session_status_returns_true_when_user_is_returning(
    authed_client: TestClient,
    fake_user: User,
) -> None:
    with patch("api.routes.conversations.has_prior_session", return_value=True) as called:
        resp = authed_client.get(
            "/sessions/prior-status",
            headers={"Authorization": "Bearer user-jwt"},
        )
    assert resp.status_code == 200
    assert resp.json() == {"is_returning_user": True}
    args, kwargs = called.call_args
    assert args[0] == fake_user
    assert kwargs == {"supabase_token": "user-jwt"}


def test_prior_session_status_returns_false_for_first_time_user(
    authed_client: TestClient,
) -> None:
    with patch("api.routes.conversations.has_prior_session", return_value=False):
        resp = authed_client.get(
            "/sessions/prior-status",
            headers={"Authorization": "Bearer user-jwt"},
        )
    assert resp.status_code == 200
    assert resp.json() == {"is_returning_user": False}


def test_prior_session_status_returns_401_without_token(client: TestClient) -> None:
    resp = client.get("/sessions/prior-status")
    assert resp.status_code == 401
    assert resp.headers.get("WWW-Authenticate") == "Bearer"
