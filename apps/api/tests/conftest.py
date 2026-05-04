"""Shared fixtures for the FastAPI test suite.

The fixtures here are intentionally tiny so they read as templates for
later tests:

- ``settings`` builds a fully-populated `Settings` with placeholder
  Supabase values so the app factory does not crash on env validation.
- ``app`` runs the factory with those settings.
- ``client`` wraps the app in a ``TestClient``.
- ``authed_client`` overrides the ``get_current_user`` dependency so a
  test can exercise an authenticated route without minting a JWT.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID

import pytest
from api.app import create_app
from core.auth import User, get_current_user
from core.config import Settings, get_settings
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def settings() -> Iterator[Settings]:
    get_settings.cache_clear()
    s = Settings(
        supabase_url="https://test.supabase.co",
        supabase_anon_key="test-anon",
        supabase_jwt_secret="test-secret",
        livekit_url="wss://test.livekit.cloud",
        livekit_api_key="lk-test-key",
        livekit_api_secret="lk-test-secret",
        openai_api_key="sk-test-openai",
    )
    yield s
    get_settings.cache_clear()


@pytest.fixture
def app(settings: Settings) -> Iterator[FastAPI]:
    instance = create_app(settings=settings)
    # The route-level dependency `Depends(get_settings)` will rebuild
    # the cached `Settings` from the process environment. Tests have no
    # such environment, so we override the dependency to return the
    # fixture-built `Settings` for the duration of the test.
    instance.dependency_overrides[get_settings] = lambda: settings
    try:
        yield instance
    finally:
        instance.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def fake_user() -> User:
    return User(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        email="alice@example.com",
    )


@pytest.fixture
def authed_client(app: FastAPI, fake_user: User) -> Iterator[TestClient]:
    """A `TestClient` whose `get_current_user` dependency returns ``fake_user``."""

    def _override() -> User:
        return fake_user

    app.dependency_overrides[get_current_user] = _override
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_current_user, None)
