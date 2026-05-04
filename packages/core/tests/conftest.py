"""Shared pytest fixtures for `core` unit tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from core.config import Settings, get_settings

_TEST_JWT_SECRET = "test-secret-do-not-use-in-production"


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
        supabase_anon_key="test-anon-key",
        supabase_jwt_secret=_TEST_JWT_SECRET,
    )
    get_settings.cache_clear()
