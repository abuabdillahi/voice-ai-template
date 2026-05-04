"""Unit tests for `core.auth`.

These exercise the four canonical token states the issue calls out:
valid → User, expired → raises, malformed → raises, missing claims →
raises. The HTTP wrapper (`get_current_user`) is covered separately
from the pure verifier so that the error-mapping code stays explicit.
"""

from __future__ import annotations

import time
from uuid import uuid4

import pytest
from core.auth import AuthError, User, get_current_user, verify_token
from core.config import Settings
from fastapi import HTTPException
from jose import jwt

_ALGORITHM = "HS256"


def _encode(payload: dict[str, object], settings: Settings) -> str:
    """Sign a token the same way Supabase does for tests."""
    return jwt.encode(payload, settings.supabase_jwt_secret, algorithm=_ALGORITHM)


def _valid_payload() -> dict[str, object]:
    return {
        "sub": str(uuid4()),
        "email": "alice@example.com",
        "aud": "authenticated",
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
    }


def test_verify_token_returns_user_for_valid_token(settings: Settings) -> None:
    payload = _valid_payload()
    token = _encode(payload, settings)

    user = verify_token(token, settings=settings)

    assert isinstance(user, User)
    assert str(user.id) == payload["sub"]
    assert user.email == payload["email"]


def test_verify_token_raises_for_expired_token(settings: Settings) -> None:
    payload = _valid_payload()
    payload["exp"] = int(time.time()) - 60
    token = _encode(payload, settings)

    with pytest.raises(AuthError):
        verify_token(token, settings=settings)


def test_verify_token_raises_for_malformed_token(settings: Settings) -> None:
    with pytest.raises(AuthError):
        verify_token("not-a-jwt", settings=settings)


def test_verify_token_raises_for_bad_signature(settings: Settings) -> None:
    payload = _valid_payload()
    token = jwt.encode(payload, "different-secret", algorithm=_ALGORITHM)

    with pytest.raises(AuthError):
        verify_token(token, settings=settings)


def test_verify_token_raises_when_sub_claim_missing(settings: Settings) -> None:
    payload = _valid_payload()
    del payload["sub"]
    token = _encode(payload, settings)

    with pytest.raises(AuthError):
        verify_token(token, settings=settings)


def test_verify_token_raises_when_email_claim_missing(settings: Settings) -> None:
    payload = _valid_payload()
    del payload["email"]
    token = _encode(payload, settings)

    with pytest.raises(AuthError):
        verify_token(token, settings=settings)


def test_verify_token_raises_when_sub_is_not_a_uuid(settings: Settings) -> None:
    payload = _valid_payload()
    payload["sub"] = "not-a-uuid"
    token = _encode(payload, settings)

    with pytest.raises(AuthError):
        verify_token(token, settings=settings)


def test_get_current_user_extracts_bearer_token(settings: Settings) -> None:
    payload = _valid_payload()
    token = _encode(payload, settings)

    user = get_current_user(authorization=f"Bearer {token}", settings=settings)

    assert user.email == payload["email"]


def test_get_current_user_raises_401_when_header_missing(settings: Settings) -> None:
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(authorization=None, settings=settings)
    assert exc_info.value.status_code == 401


def test_get_current_user_raises_401_for_non_bearer_scheme(settings: Settings) -> None:
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(authorization="Basic abc123", settings=settings)
    assert exc_info.value.status_code == 401


def test_get_current_user_raises_401_for_invalid_token(settings: Settings) -> None:
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(authorization="Bearer not-a-jwt", settings=settings)
    assert exc_info.value.status_code == 401
