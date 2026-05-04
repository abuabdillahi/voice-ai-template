"""Unit tests for `core.config`."""

from __future__ import annotations

import pytest
from core.config import Settings, get_settings


def test_settings_parses_cors_origins() -> None:
    settings = Settings(
        supabase_url="https://example.supabase.co",
        supabase_publishable_key="publishable",
        livekit_url="wss://example.livekit.cloud",
        livekit_api_key="lk-key",
        livekit_api_secret="lk-secret",
        openai_api_key="sk-openai",
        cors_origins="http://localhost:5173, https://app.example.com ,",
    )
    assert settings.cors_origin_list == [
        "http://localhost:5173",
        "https://app.example.com",
    ]


def test_settings_accepts_legacy_anon_key_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    """Backward compat: SUPABASE_ANON_KEY still resolves into supabase_publishable_key."""
    get_settings.cache_clear()
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "legacy-anon")
    monkeypatch.setenv("LIVEKIT_URL", "wss://example.livekit.cloud")
    monkeypatch.setenv("LIVEKIT_API_KEY", "lk-key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "lk-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")

    settings = Settings()  # type: ignore[call-arg]
    assert settings.supabase_publishable_key == "legacy-anon"
    get_settings.cache_clear()


def test_get_settings_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "publishable")
    monkeypatch.setenv("LIVEKIT_URL", "wss://example.livekit.cloud")
    monkeypatch.setenv("LIVEKIT_API_KEY", "lk-key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "lk-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")

    a = get_settings()
    b = get_settings()
    assert a is b
    get_settings.cache_clear()
