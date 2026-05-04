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


# ---------------------------------------------------------------------------
# Issue 10 — PUT /preferences/{key}
# ---------------------------------------------------------------------------


def test_put_preference_returns_200_on_valid_value(
    authed_client: TestClient,
    fake_user: User,
) -> None:
    with patch("api.routes.preferences.set") as set_mock:
        resp = authed_client.put(
            "/preferences/preferred_name",
            headers={"Authorization": "Bearer user-jwt"},
            json={"value": "Sam"},
        )
    assert resp.status_code == 200
    assert resp.json() == {"key": "preferred_name", "value": "Sam"}
    # The route must propagate the user, key, validated value, and the
    # bearer token to the core layer so RLS applies on the upsert.
    set_mock.assert_called_once()
    args, kwargs = set_mock.call_args
    assert args == (fake_user, "preferred_name", "Sam")
    assert kwargs == {"access_token": "user-jwt"}


def test_put_preference_trims_whitespace_for_preferred_name(
    authed_client: TestClient,
) -> None:
    with patch("api.routes.preferences.set") as set_mock:
        resp = authed_client.put(
            "/preferences/preferred_name",
            headers={"Authorization": "Bearer user-jwt"},
            json={"value": "  Sam  "},
        )
    assert resp.status_code == 200
    assert resp.json()["value"] == "Sam"
    args, _ = set_mock.call_args
    assert args[2] == "Sam"


def test_put_preference_returns_200_for_known_voice(
    authed_client: TestClient,
) -> None:
    with patch("api.routes.preferences.set"):
        resp = authed_client.put(
            "/preferences/voice",
            headers={"Authorization": "Bearer user-jwt"},
            json={"value": "alloy"},
        )
    assert resp.status_code == 200


def test_put_preference_returns_400_on_unknown_key(authed_client: TestClient) -> None:
    with patch("api.routes.preferences.set") as set_mock:
        resp = authed_client.put(
            "/preferences/totally_made_up",
            headers={"Authorization": "Bearer user-jwt"},
            json={"value": "anything"},
        )
    assert resp.status_code == 400
    body = resp.json()
    assert body["detail"]["code"] == "invalid_preference"
    set_mock.assert_not_called()


def test_put_preference_returns_400_on_invalid_voice(authed_client: TestClient) -> None:
    with patch("api.routes.preferences.set") as set_mock:
        resp = authed_client.put(
            "/preferences/voice",
            headers={"Authorization": "Bearer user-jwt"},
            json={"value": "not-a-voice"},
        )
    assert resp.status_code == 400
    set_mock.assert_not_called()


def test_put_preference_returns_400_on_empty_preferred_name(
    authed_client: TestClient,
) -> None:
    with patch("api.routes.preferences.set") as set_mock:
        resp = authed_client.put(
            "/preferences/preferred_name",
            headers={"Authorization": "Bearer user-jwt"},
            json={"value": "   "},
        )
    assert resp.status_code == 400
    set_mock.assert_not_called()


def test_put_preference_returns_401_without_auth(client: TestClient) -> None:
    resp = client.put(
        "/preferences/preferred_name",
        json={"value": "Sam"},
    )
    assert resp.status_code == 401
