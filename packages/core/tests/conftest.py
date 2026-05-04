"""Shared pytest fixtures for `core` unit tests."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from core.config import Settings, get_settings

# Disable the testcontainers reaper. With multiple module-scoped Postgres
# fixtures across the integration suite, the reaper races itself on
# startup and pytest dies with a 409 container-name conflict. The reaper
# only adds value when the test process crashes hard; the integration
# tests use ``with PostgresContainer(...) as pg`` which already cleans
# up on a graceful exit. ``setdefault`` so a CI job (or a developer)
# can still flip it back on for a one-off run.
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")


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
