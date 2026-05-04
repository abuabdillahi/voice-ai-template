"""Unit tests for `core.auth`.

Issue 13 swapped the verifier from a shared HS256 secret to JWKS-based
asymmetric verification. The tests now generate an in-test EC keypair,
sign synthetic JWTs with the private key, and serve the public key via
a `httpx.MockTransport` so the real `core.jwks.get_jwks` HTTP path is
exercised end-to-end without ever leaving the process.

Canonical token states covered: valid, expired, malformed, bad
signature (signed with a different key), missing claims, non-UUID sub.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import httpx
import pytest
from core import jwks as core_jwks
from core.auth import AuthError, User, get_current_user, verify_token
from core.config import Settings
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from jose import jwt
from jose.utils import long_to_base64

_ALGORITHM = "ES256"
_KID = "test-kid-1"


def _ec_keypair() -> tuple[ec.EllipticCurvePrivateKey, dict[str, Any]]:
    """Generate a P-256 EC keypair and return (private_key, jwk_public)."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_numbers = private_key.public_key().public_numbers()
    jwk_public = {
        "kty": "EC",
        "crv": "P-256",
        "x": long_to_base64(public_numbers.x, size=32).decode("ascii"),
        "y": long_to_base64(public_numbers.y, size=32).decode("ascii"),
        "alg": _ALGORITHM,
        "use": "sig",
        "kid": _KID,
    }
    return private_key, jwk_public


def _private_pem(private_key: ec.EllipticCurvePrivateKey) -> bytes:
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


@pytest.fixture
def keypair() -> tuple[ec.EllipticCurvePrivateKey, dict[str, Any]]:
    return _ec_keypair()


@pytest.fixture
def jwks_doc(keypair: tuple[ec.EllipticCurvePrivateKey, dict[str, Any]]) -> dict[str, Any]:
    _, jwk_public = keypair
    return {"keys": [jwk_public]}


@pytest.fixture(autouse=True)
def _patch_jwks(monkeypatch: pytest.MonkeyPatch, jwks_doc: dict[str, Any]) -> Iterator[None]:
    """Stub the JWKS fetch so verify_token never hits the network.

    Also clears the module-global cache before and after each test so
    one test's keys cannot bleed into the next.
    """
    core_jwks._cache = None  # type: ignore[attr-defined]

    def _fake_get_jwks(_url: str, *, ttl_seconds: int = 600) -> dict[str, Any]:  # noqa: ARG001
        return jwks_doc

    monkeypatch.setattr("core.auth.get_jwks", _fake_get_jwks)
    yield
    core_jwks._cache = None  # type: ignore[attr-defined]


def _encode(
    payload: dict[str, Any],
    private_key: ec.EllipticCurvePrivateKey,
    *,
    kid: str = _KID,
) -> str:
    """Sign a token the same way Supabase does for tests (ES256)."""
    return jwt.encode(
        payload,
        _private_pem(private_key),
        algorithm=_ALGORITHM,
        headers={"kid": kid},
    )


def _valid_payload() -> dict[str, Any]:
    return {
        "sub": str(uuid4()),
        "email": "alice@example.com",
        "aud": "authenticated",
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
    }


def test_verify_token_returns_user_for_valid_token(
    settings: Settings,
    keypair: tuple[ec.EllipticCurvePrivateKey, dict[str, Any]],
) -> None:
    private_key, _ = keypair
    payload = _valid_payload()
    token = _encode(payload, private_key)

    user = verify_token(token, settings=settings)

    assert isinstance(user, User)
    assert str(user.id) == payload["sub"]
    assert user.email == payload["email"]


def test_verify_token_raises_for_expired_token(
    settings: Settings,
    keypair: tuple[ec.EllipticCurvePrivateKey, dict[str, Any]],
) -> None:
    private_key, _ = keypair
    payload = _valid_payload()
    payload["exp"] = int(time.time()) - 60
    token = _encode(payload, private_key)

    with pytest.raises(AuthError):
        verify_token(token, settings=settings)


def test_verify_token_raises_for_malformed_token(settings: Settings) -> None:
    with pytest.raises(AuthError):
        verify_token("not-a-jwt", settings=settings)


def test_verify_token_raises_for_bad_signature(settings: Settings) -> None:
    """A token signed with a different key is rejected."""
    other_key = ec.generate_private_key(ec.SECP256R1())
    payload = _valid_payload()
    token = jwt.encode(
        payload,
        _private_pem(other_key),
        algorithm=_ALGORITHM,
        headers={"kid": _KID},
    )

    with pytest.raises(AuthError):
        verify_token(token, settings=settings)


def test_verify_token_raises_when_sub_claim_missing(
    settings: Settings,
    keypair: tuple[ec.EllipticCurvePrivateKey, dict[str, Any]],
) -> None:
    private_key, _ = keypair
    payload = _valid_payload()
    del payload["sub"]
    token = _encode(payload, private_key)

    with pytest.raises(AuthError):
        verify_token(token, settings=settings)


def test_verify_token_raises_when_email_claim_missing(
    settings: Settings,
    keypair: tuple[ec.EllipticCurvePrivateKey, dict[str, Any]],
) -> None:
    private_key, _ = keypair
    payload = _valid_payload()
    del payload["email"]
    token = _encode(payload, private_key)

    with pytest.raises(AuthError):
        verify_token(token, settings=settings)


def test_verify_token_raises_when_sub_is_not_a_uuid(
    settings: Settings,
    keypair: tuple[ec.EllipticCurvePrivateKey, dict[str, Any]],
) -> None:
    private_key, _ = keypair
    payload = _valid_payload()
    payload["sub"] = "not-a-uuid"
    token = _encode(payload, private_key)

    with pytest.raises(AuthError):
        verify_token(token, settings=settings)


def test_verify_token_refetches_jwks_on_kid_miss(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a token's kid isn't in the cached JWKS, we refetch once.

    This absorbs Supabase key rotations without operator intervention.
    """
    private_key, jwk_public = _ec_keypair()
    jwk_public["kid"] = "rotated-kid"
    initial_jwks: dict[str, Any] = {"keys": []}  # cache starts stale
    fresh_jwks = {"keys": [jwk_public]}
    fetch_count = {"n": 0}

    def _fake_get_jwks(_url: str, *, ttl_seconds: int = 600) -> dict[str, Any]:  # noqa: ARG001
        fetch_count["n"] += 1
        return initial_jwks if fetch_count["n"] == 1 else fresh_jwks

    monkeypatch.setattr("core.auth.get_jwks", _fake_get_jwks)

    payload = _valid_payload()
    token = _encode(payload, private_key, kid="rotated-kid")

    user = verify_token(token, settings=settings)
    assert user.email == payload["email"]
    assert fetch_count["n"] == 2  # initial miss + one refetch


def test_get_current_user_extracts_bearer_token(
    settings: Settings,
    keypair: tuple[ec.EllipticCurvePrivateKey, dict[str, Any]],
) -> None:
    private_key, _ = keypair
    payload = _valid_payload()
    token = _encode(payload, private_key)

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


def test_get_jwks_caches_within_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    """The JWKS module reuses a fetched document until the TTL expires."""
    core_jwks._cache = None  # type: ignore[attr-defined]
    fetch_count = {"n": 0}

    def _handler(_request: httpx.Request) -> httpx.Response:
        fetch_count["n"] += 1
        return httpx.Response(200, json={"keys": []})

    transport = httpx.MockTransport(_handler)
    real_client = httpx.Client

    def _patched_client(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs.setdefault("transport", transport)
        return real_client(*args, **kwargs)

    monkeypatch.setattr("core.jwks.httpx.Client", _patched_client)

    a = core_jwks.get_jwks("https://example.supabase.co/jwks.json")
    b = core_jwks.get_jwks("https://example.supabase.co/jwks.json")
    assert a is b
    assert fetch_count["n"] == 1
    core_jwks.invalidate_jwks()
    c = core_jwks.get_jwks("https://example.supabase.co/jwks.json")
    assert fetch_count["n"] == 2
    assert json.dumps(c) == json.dumps({"keys": []})
    core_jwks._cache = None  # type: ignore[attr-defined]
