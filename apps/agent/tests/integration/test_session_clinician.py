"""Integration test for the `find_clinician` flow.

Mirrors the contract-shaped approach used elsewhere in this directory:
rather than spin up a LiveKit harness, we drive the same code paths
the harness would (tool dispatch → tool-result forwarding → message
persistence) with the upstream HTTP boundary mocked. Together with the
unit tests on :mod:`core.clinician` and :mod:`core.tools.triage` this
covers the contract end-to-end.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import httpx
import pytest
import structlog
from agent.session import (
    TOOL_CALLS_TOPIC,
    _persist_tool_message,
    _SessionDeps,
)
from core import clinician
from core.auth import User
from core.config import Settings
from core.tools import dispatch
from core.tools.registry import ToolContext


def _settings() -> Settings:
    return Settings(  # type: ignore[arg-type]
        supabase_url="https://test.supabase.co",
        supabase_publishable_key="test-publishable",
        supabase_jwks_url="https://test.supabase.co/auth/v1/.well-known/jwks.json",
        livekit_url="wss://test.livekit.cloud",
        livekit_api_key="lk-test-key",  # pragma: allowlist secret
        livekit_api_secret="lk-test-secret",  # pragma: allowlist secret
        openai_api_key="sk-test-openai",  # pragma: allowlist secret
        osm_contact_email="ops@example.com",
        nominatim_base_url="https://nominatim.example.com",
        overpass_base_url="https://overpass.example.com/api",
    )


def _user() -> User:
    return User(id=UUID("11111111-1111-1111-1111-111111111111"), email="alice@example.com")


def _deps() -> _SessionDeps:
    return _SessionDeps(
        user=_user(),
        log=structlog.get_logger("test"),
        session_id="sess-1",
        supabase_access_token="user-jwt",
    )


def _patch_async_client(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    real_init = httpx.AsyncClient.__init__

    def _patched_init(self: httpx.AsyncClient, *args: Any, **kwargs: Any) -> None:
        async def _async(request: httpx.Request) -> httpx.Response:
            return handler(request)

        kwargs["transport"] = httpx.MockTransport(_async)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", _patched_init)


@pytest.fixture(autouse=True)
def _reset_clinician(monkeypatch: pytest.MonkeyPatch) -> None:
    clinician._clear_cache_for_tests()
    monkeypatch.setattr(clinician, "_NOMINATIM_RATE_LIMIT_INTERVAL_SECONDS", 0.0)
    # Stub get_settings so the tool wrapper sees osm_contact_email set.
    from core import config

    config.get_settings.cache_clear()
    monkeypatch.setattr("core.tools.triage.get_settings", _settings)


@pytest.mark.asyncio
async def test_find_clinician_end_to_end_with_mocked_osm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tool dispatch returns the structured payload the wrapper forwards."""

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "nominatim.example.com":
            return httpx.Response(
                200,
                json=[
                    {
                        "display_name": "Brooklyn, Kings County, New York, United States",
                        "lat": "40.6501",
                        "lon": "-73.9496",
                    }
                ],
            )
        return httpx.Response(
            200,
            json={
                "elements": [
                    {
                        "type": "node",
                        "id": 11,
                        "lat": 40.652,
                        "lon": -73.951,
                        "tags": {
                            "name": "Park PT",
                            "healthcare": "physiotherapist",
                            "phone": "+1 718-555-0100",
                            "addr:housenumber": "123",
                            "addr:street": "Atlantic Ave",
                            "addr:city": "Brooklyn",
                        },
                    }
                ]
            },
        )

    _patch_async_client(monkeypatch, _handler)

    deps = _deps()
    ctx = ToolContext(
        user=deps.user,
        log=deps.log,
        session_id=deps.session_id,
        supabase_access_token=deps.supabase_access_token,
    )
    raw = await dispatch(
        "find_clinician",
        {"condition_id": "carpal_tunnel", "location": "Brooklyn"},
        ctx,
    )
    assert isinstance(raw, str)
    payload = json.loads(raw)
    assert "error" not in payload
    assert payload["specialist_label"] == "physiotherapist or occupational therapist"
    assert payload["location_resolved"] == "Brooklyn, Kings County, New York, United States"
    assert payload["radius_km"] == 10
    assert payload["count"] == 1
    assert payload["results"][0]["name"] == "Park PT"


@pytest.mark.asyncio
async def test_find_clinician_result_forwards_on_tool_calls_topic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tool's JSON payload lands on `lk.tool-calls` verbatim."""
    sent: list[dict[str, Any]] = []

    async def _send_text(payload: str, *, topic: str) -> None:
        sent.append({"payload": json.loads(payload), "topic": topic})

    local_participant = MagicMock()
    local_participant.send_text = AsyncMock(side_effect=_send_text)

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "nominatim.example.com":
            return httpx.Response(
                200,
                json=[{"display_name": "Brooklyn", "lat": "40.65", "lon": "-73.95"}],
            )
        return httpx.Response(
            200,
            json={
                "elements": [
                    {
                        "type": "node",
                        "id": 7,
                        "lat": 40.65,
                        "lon": -73.95,
                        "tags": {"name": "Atlantic Rehab", "healthcare": "physiotherapist"},
                    }
                ]
            },
        )

    _patch_async_client(monkeypatch, _handler)

    deps = _deps()
    ctx = ToolContext(
        user=deps.user,
        log=deps.log,
        session_id=deps.session_id,
        supabase_access_token=deps.supabase_access_token,
    )
    raw = await dispatch(
        "find_clinician",
        {"condition_id": "carpal_tunnel", "location": "Brooklyn"},
        ctx,
    )

    # Simulate the forwarding the wiring helper would do: send a
    # `{name, args, result, error}` payload on the lk.tool-calls topic.
    forward_payload = {
        "id": "call-1",
        "name": "find_clinician",
        "args": {"condition_id": "carpal_tunnel", "location": "Brooklyn"},
        "result": raw,
        "error": False,
    }
    await local_participant.send_text(json.dumps(forward_payload), topic=TOOL_CALLS_TOPIC)

    assert len(sent) == 1
    sent_event = sent[0]
    assert sent_event["topic"] == "lk.tool-calls"
    assert sent_event["payload"]["name"] == "find_clinician"
    assert sent_event["payload"]["error"] is False
    inner = json.loads(sent_event["payload"]["result"])
    assert inner["specialist_label"] == "physiotherapist or occupational therapist"
    assert inner["count"] == 1
    assert inner["results"][0]["name"] == "Atlantic Rehab"


def test_find_clinician_tool_result_persists_to_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The persistence helper writes a tool row carrying the JSON payload."""
    captured: list[dict[str, Any]] = []
    insert_payload: dict[str, Any] = {}

    class _RecordingClient:
        def table(self, name: str) -> Any:
            self._table = name
            return self

        def insert(self, payload: dict[str, Any]) -> Any:
            insert_payload.update(payload)
            captured.append({"table": self._table, "payload": payload})
            return self

        def execute(self) -> Any:
            return MagicMock(
                data=[{"id": "msg-1", **insert_payload, "created_at": "2026-05-04T00:00:00+00:00"}]
            )

    monkeypatch.setattr("core.conversations.get_user_client", lambda *_a, **_k: _RecordingClient())

    log = structlog.get_logger("test")
    payload_str = json.dumps(
        {
            "specialist_label": "physiotherapist or occupational therapist",
            "location_resolved": "Brooklyn",
            "radius_km": 10,
            "results": [
                {
                    "name": "Park PT",
                    "address": "x",
                    "phone": "y",
                    "url": "z",
                    "distance_km": 1.2,
                }
            ],
            "count": 1,
        }
    )
    _persist_tool_message(
        conv_id=UUID("33333333-3333-3333-3333-333333333333"),
        supabase_token="user-jwt",
        log=log,
        tool_name="find_clinician",
        tool_args={"condition_id": "carpal_tunnel", "location": "Brooklyn"},
        tool_result=payload_str,
    )

    assert len(captured) == 1
    payload = captured[0]["payload"]
    assert payload["role"] == "tool"
    assert payload["tool_name"] == "find_clinician"
    assert payload["tool_args"] == {"condition_id": "carpal_tunnel", "location": "Brooklyn"}
    # The wrapper preserves the JSON-encoded payload as the tool_result.
    parsed = json.loads(payload["tool_result"])
    assert parsed["specialist_label"] == "physiotherapist or occupational therapist"
    assert parsed["count"] == 1
    assert parsed["results"][0]["name"] == "Park PT"
