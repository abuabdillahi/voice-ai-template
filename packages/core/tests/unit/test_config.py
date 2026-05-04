"""Unit tests for `core.config`."""

from __future__ import annotations

import pytest
from core.config import Settings, get_settings


def test_settings_parses_cors_origins() -> None:
    settings = Settings(
        supabase_url="https://example.supabase.co",
        supabase_anon_key="anon",
        supabase_jwt_secret="secret",
        cors_origins="http://localhost:5173, https://app.example.com ,",
    )
    assert settings.cors_origin_list == [
        "http://localhost:5173",
        "https://app.example.com",
    ]


def test_get_settings_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "secret")

    a = get_settings()
    b = get_settings()
    assert a is b
    get_settings.cache_clear()
