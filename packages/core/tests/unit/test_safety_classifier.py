"""Unit tests for the gpt-4o-mini safety classifier.

The OpenAI client is mocked at :class:`openai.AsyncOpenAI` so the
suite runs offline. Each tier returns the expected shape; failure
modes (timeout, malformed JSON, missing tier) degrade to a NONE
result with a logged warning rather than raising.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from core import safety
from core.config import Settings


def _settings() -> Settings:
    return Settings(
        supabase_url="https://test.supabase.co",
        supabase_publishable_key="test-publishable",
        supabase_jwks_url="https://test.supabase.co/auth/v1/.well-known/jwks.json",
        livekit_url="wss://test.livekit.cloud",
        livekit_api_key="lk-test-key",  # pragma: allowlist secret
        livekit_api_secret="lk-test-secret",  # pragma: allowlist secret
        openai_api_key="sk-test-openai",  # pragma: allowlist secret
    )


def _mock_openai(monkeypatch: pytest.MonkeyPatch, *, content: str | None) -> AsyncMock:
    """Patch :class:`openai.AsyncOpenAI` to return ``content`` from chat.completions."""
    create_mock = AsyncMock()
    if content is None:
        choices: list[Any] = []
    else:
        msg = MagicMock()
        msg.content = content
        choice = MagicMock()
        choice.message = msg
        choices = [choice]
    response = MagicMock()
    response.choices = choices
    create_mock.return_value = response

    class _FakeAsyncClient:
        def __init__(self, **_kwargs: Any) -> None:
            self.chat = MagicMock()
            self.chat.completions = MagicMock()
            self.chat.completions.create = create_mock

    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeAsyncClient)
    return create_mock


@pytest.mark.parametrize(
    ("tier_string", "expected_tier", "matched"),
    [
        ("emergent", safety.RedFlagTier.EMERGENT, ["chest_pain"]),
        ("urgent", safety.RedFlagTier.URGENT, ["saddle_anaesthesia"]),
        ("clinician_soon", safety.RedFlagTier.CLINICIAN_SOON, ["chronic_persistent"]),
    ],
)
@pytest.mark.asyncio
async def test_classify_returns_expected_shape_for_each_non_none_tier(
    monkeypatch: pytest.MonkeyPatch,
    tier_string: str,
    expected_tier: safety.RedFlagTier,
    matched: list[str],
) -> None:
    create = _mock_openai(
        monkeypatch,
        content=json.dumps({"tier": tier_string, "matched_flags": matched}),
    )
    result = await safety.classify(
        "my heart is racing and my chest feels weird", settings=_settings()
    )
    assert result.tier is expected_tier
    assert list(result.matched_flags) == matched
    assert result.source == "classifier"
    create.assert_awaited_once()
    kwargs = create.await_args.kwargs
    assert kwargs["model"] == "gpt-4o-mini"
    # Structured output is the contract — pin that the request asks
    # for the json_schema response_format.
    assert kwargs["response_format"]["type"] == "json_schema"


@pytest.mark.asyncio
async def test_classify_returns_none_for_empty_utterance() -> None:
    result = await safety.classify("   ", settings=_settings())
    assert result.tier is safety.RedFlagTier.NONE
    assert result.matched_flags == ()


@pytest.mark.asyncio
async def test_classify_returns_none_when_openai_api_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeAsyncClient:
        def __init__(self, **_kwargs: Any) -> None:
            self.chat = MagicMock()
            self.chat.completions = MagicMock()
            self.chat.completions.create = AsyncMock(side_effect=TimeoutError("boom"))

    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeAsyncClient)

    result = await safety.classify("chest pain", settings=_settings())
    assert result.tier is safety.RedFlagTier.NONE
    assert result.source == "classifier"


@pytest.mark.asyncio
async def test_classify_returns_none_for_malformed_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_openai(monkeypatch, content="not json")
    result = await safety.classify("chest pain", settings=_settings())
    assert result.tier is safety.RedFlagTier.NONE


@pytest.mark.asyncio
async def test_classify_returns_none_for_unknown_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_openai(
        monkeypatch,
        content=json.dumps({"tier": "marshmallow", "matched_flags": []}),
    )
    result = await safety.classify("chest pain", settings=_settings())
    assert result.tier is safety.RedFlagTier.NONE


@pytest.mark.asyncio
async def test_classify_returns_none_for_empty_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_openai(monkeypatch, content=None)
    result = await safety.classify("chest pain", settings=_settings())
    assert result.tier is safety.RedFlagTier.NONE


@pytest.mark.asyncio
async def test_classify_uses_configured_model_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create = _mock_openai(
        monkeypatch,
        content=json.dumps({"tier": "none", "matched_flags": []}),
    )
    settings = Settings(
        supabase_url="https://test.supabase.co",
        supabase_publishable_key="test-publishable",
        supabase_jwks_url="https://test.supabase.co/auth/v1/.well-known/jwks.json",
        livekit_url="wss://test.livekit.cloud",
        livekit_api_key="lk-test-key",  # pragma: allowlist secret
        livekit_api_secret="lk-test-secret",  # pragma: allowlist secret
        openai_api_key="sk-test-openai",  # pragma: allowlist secret
        safety_classifier_model="gpt-5-mini-future",
    )
    await safety.classify("chest pain", settings=settings)
    assert create.await_args.kwargs["model"] == "gpt-5-mini-future"


def test_classifier_system_prompt_names_each_tier() -> None:
    prompt = safety.CLASSIFIER_SYSTEM_PROMPT
    assert '"emergent"' in prompt
    assert '"urgent"' in prompt
    assert '"clinician_soon"' in prompt
    assert '"none"' in prompt
