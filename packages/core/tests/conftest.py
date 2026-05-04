"""Shared pytest fixtures for `core` unit tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from core.config import Settings, get_settings


@pytest.fixture
def settings() -> Iterator[Settings]:
    """Provide a fully-populated `Settings` instance for unit tests.

    The `get_settings()` cache is cleared before and after the test so
    that tests can mutate environment variables freely without leaking
    into one another.
    """
    get_settings.cache_clear()
    yield Settings(
        supabase_url="https://test.supabase.co",
        supabase_publishable_key="test-publishable-key",
        supabase_jwks_url="https://test.supabase.co/auth/v1/.well-known/jwks.json",
        livekit_url="wss://test.livekit.cloud",
        livekit_api_key="lk-test-key",
        livekit_api_secret="lk-test-secret",
        openai_api_key="sk-test-openai",
    )
    get_settings.cache_clear()
