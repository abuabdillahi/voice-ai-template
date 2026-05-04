"""Tests for the `/preferences` route.

Asserts the externally-observable behaviour: status codes, response
shape, and that the user's bearer token reaches `core.preferences.list`
unchanged. The underlying Supabase round-trip is mocked at the
`core.preferences.list` boundary — the integration test in `core`
covers the real database path.
"""

from __future__ import annotations

from unittest.mock import patch

from core.auth import User
from fastapi.testclient import TestClient


def test_preferences_returns_dict_when_authenticated(
    authed_client: TestClient,
    fake_user: User,
) -> None:
    fake_rows = {"favorite_color": "blue", "preferred_name": "Alice"}
    with patch("api.routes.preferences.list", return_value=fake_rows) as listed:
        resp = authed_client.get(
            "/preferences",
            headers={"Authorization": "Bearer user-jwt"},
        )
    assert resp.status_code == 200
    assert resp.json() == {"preferences": fake_rows}
    # The route must hand the user's token to the core layer so RLS
    # applies on the real Supabase round-trip.
    listed.assert_called_once()
    args, kwargs = listed.call_args
    assert args[0] == fake_user
    assert kwargs == {"access_token": "user-jwt"}


def test_preferences_returns_empty_dict_when_user_has_no_rows(
    authed_client: TestClient,
) -> None:
    with patch("api.routes.preferences.list", return_value={}):
        resp = authed_client.get(
            "/preferences",
            headers={"Authorization": "Bearer user-jwt"},
        )
    assert resp.status_code == 200
    assert resp.json() == {"preferences": {}}


def test_preferences_returns_401_without_token(client: TestClient) -> None:
    resp = client.get("/preferences")
    assert resp.status_code == 401
    assert resp.headers.get("WWW-Authenticate") == "Bearer"
