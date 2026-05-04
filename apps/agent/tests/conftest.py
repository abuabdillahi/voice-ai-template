"""Shared fixtures for the agent test suite."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from core.config import Settings, get_settings


@pytest.fixture
def settings() -> Iterator[Settings]:
    get_settings.cache_clear()
    yield Settings(
        supabase_url="https://test.supabase.co",
        supabase_anon_key="test-anon",
        supabase_jwt_secret="test-secret",
        livekit_url="wss://test.livekit.cloud",
        livekit_api_key="lk-test-key",
        livekit_api_secret="lk-test-secret",
        openai_api_key="sk-test-openai",
    )
    get_settings.cache_clear()
