"""Unit tests for the model-callable `escalate` tool."""

from __future__ import annotations

import importlib
import json
from collections.abc import Iterator
from uuid import UUID

import pytest
import structlog
from core.auth import User
from core.tools import dispatch, get_tool
from core.tools.registry import ToolContext


@pytest.fixture(autouse=True)
def _ensure_registered() -> Iterator[None]:
    """Re-register the triage tools per test (registry is mutable global)."""
    from core.tools import triage as triage_tools

    importlib.reload(triage_tools)
    yield


def _ctx() -> ToolContext:
    return ToolContext(
        user=User(id=UUID("11111111-1111-1111-1111-111111111111"), email="alice@example.com"),
        log=structlog.get_logger("test"),
        session_id="sess-1",
    )


def test_escalate_is_registered() -> None:
    schema = get_tool("escalate")
    assert schema is not None
    assert "tier" in schema.parameters["properties"]
    assert "reason" in schema.parameters["properties"]


@pytest.mark.asyncio
async def test_escalate_returns_scripted_message_for_each_tier() -> None:
    for tier in ("emergent", "urgent", "clinician_soon"):
        result = await dispatch(
            "escalate",
            {"tier": tier, "reason": "user reported a relevant red-flag symptom"},
            _ctx(),
        )
        payload = json.loads(result)
        assert payload["tier"] == tier
        assert payload["reason"] == "user reported a relevant red-flag symptom"
        assert payload["script"]
        assert len(payload["script"]) > 50


@pytest.mark.asyncio
async def test_escalate_rejects_unknown_tier() -> None:
    result = await dispatch(
        "escalate",
        {"tier": "marshmallow", "reason": "test"},
        _ctx(),
    )
    payload = json.loads(result)
    assert "error" in payload
    assert "marshmallow" in payload["error"]


@pytest.mark.asyncio
async def test_escalate_emergent_script_contains_emergency_number() -> None:
    result = await dispatch(
        "escalate",
        {"tier": "emergent", "reason": "chest pain"},
        _ctx(),
    )
    payload = json.loads(result)
    script = payload["script"].lower()
    assert "911" in script or "999" in script or "112" in script
