"""Unit tests for :mod:`core.tools.triage`.

Asserts the model-callable tool's contract — schema shape, dispatch
happy path, and the in-process state side-effect.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from uuid import UUID

import pytest
import structlog
from core import triage
from core.auth import User
from core.tools import dispatch, get_tool
from core.tools.registry import ToolContext


@pytest.fixture(autouse=True)
def _isolate_state() -> Iterator[None]:
    """Reset slot store and ensure triage tools are registered.

    The tool registry's `_clear_registry_for_tests` (used by
    ``test_tools_registry.py``) wipes module-level state; reloading
    :mod:`core.tools.triage` re-runs its ``@tool`` decoration so the
    triage tools are present regardless of test execution order.
    """
    import importlib

    from core.tools import triage as triage_tools

    importlib.reload(triage_tools)
    triage._STATES.clear()  # noqa: SLF001
    yield
    triage._STATES.clear()  # noqa: SLF001


def _ctx(session_id: str = "sess-1") -> ToolContext:
    return ToolContext(
        user=User(id=UUID("11111111-1111-1111-1111-111111111111"), email="alice@example.com"),
        log=structlog.get_logger("test"),
        session_id=session_id,
    )


def test_record_symptom_is_registered() -> None:
    schema = get_tool("record_symptom")
    assert schema is not None
    # The schema must list the slot vocabulary in its description so
    # the realtime model knows which slot names are valid.
    for slot in triage.SLOT_NAMES:
        assert slot in schema.description


def test_record_symptom_schema_requires_slot_and_value() -> None:
    schema = get_tool("record_symptom")
    assert schema is not None
    assert schema.parameters["properties"].keys() == {"slot", "value"}
    assert set(schema.parameters.get("required", [])) == {"slot", "value"}


@pytest.mark.asyncio
async def test_dispatch_record_symptom_writes_to_slot_store() -> None:
    result = await dispatch(
        "record_symptom",
        {"slot": "location", "value": "right wrist"},
        _ctx(),
    )
    assert isinstance(result, str)
    payload = json.loads(result)
    assert payload["state"] == {"location": "right wrist"}
    assert triage.get_state("sess-1") == {"location": "right wrist"}


@pytest.mark.asyncio
async def test_dispatch_record_symptom_returns_full_state_after_multiple_calls() -> None:
    await dispatch("record_symptom", {"slot": "location", "value": "wrist"}, _ctx())
    result = await dispatch(
        "record_symptom",
        {"slot": "onset", "value": "last week"},
        _ctx(),
    )
    payload = json.loads(result)
    assert payload["state"] == {"location": "wrist", "onset": "last week"}


@pytest.mark.asyncio
async def test_dispatch_record_symptom_isolates_sessions() -> None:
    await dispatch("record_symptom", {"slot": "location", "value": "wrist"}, _ctx("sess-a"))
    await dispatch(
        "record_symptom",
        {"slot": "location", "value": "lower back"},
        _ctx("sess-b"),
    )
    assert triage.get_state("sess-a") == {"location": "wrist"}
    assert triage.get_state("sess-b") == {"location": "lower back"}


@pytest.mark.asyncio
async def test_dispatch_record_symptom_returns_error_for_unknown_slot() -> None:
    result = await dispatch(
        "record_symptom",
        {"slot": "marshmallow", "value": "irrelevant"},
        _ctx(),
    )
    payload = json.loads(result)
    assert "error" in payload
    assert "marshmallow" in payload["error"]
    # The tool returns a structured error rather than crashing the
    # session so the realtime model can apologise verbally.
    assert "state" in payload


@pytest.mark.asyncio
async def test_dispatch_record_symptom_without_session_id_returns_error() -> None:
    ctx = ToolContext(
        user=User(id=UUID("11111111-1111-1111-1111-111111111111"), email="a@b"),
        log=structlog.get_logger("test"),
        session_id="",
    )
    result = await dispatch("record_symptom", {"slot": "location", "value": "wrist"}, ctx)
    payload = json.loads(result)
    assert "error" in payload
    assert "session" in payload["error"].lower()


# ---------------------------------------------------------------------------
# find_clinician tool
# ---------------------------------------------------------------------------


def test_find_clinician_is_registered() -> None:
    schema = get_tool("find_clinician")
    assert schema is not None
    assert schema.name == "find_clinician"
    # The condition_id and location parameters are required.
    assert set(schema.parameters["properties"].keys()) == {"condition_id", "location"}
    assert set(schema.parameters.get("required", [])) == {"condition_id", "location"}


@pytest.mark.asyncio
async def test_find_clinician_unknown_condition_returns_taxonomy_row_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Should return the failure-taxonomy row #1 string without ever
    # touching `core.clinician.find_clinics`.
    from core.tools import triage as triage_tools

    sentinel: dict[str, bool] = {"called": False}

    async def _stub(*_args: object, **_kwargs: object) -> str:
        sentinel["called"] = True
        return "{}"

    monkeypatch.setattr(triage_tools.clinician, "find_clinics", _stub)

    result = await dispatch(
        "find_clinician",
        {"condition_id": "made_up", "location": "Brooklyn"},
        _ctx(),
    )
    payload = json.loads(result)
    assert "error" in payload
    assert "I don't have a referral path for that condition" in payload["error"]
    assert sentinel["called"] is False


@pytest.mark.asyncio
async def test_find_clinician_empty_location_returns_taxonomy_row_two(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.tools import triage as triage_tools

    sentinel: dict[str, bool] = {"called": False}

    async def _stub(*_args: object, **_kwargs: object) -> str:
        sentinel["called"] = True
        return "{}"

    monkeypatch.setattr(triage_tools.clinician, "find_clinics", _stub)

    result = await dispatch(
        "find_clinician",
        {"condition_id": "carpal_tunnel", "location": "   "},
        _ctx(),
    )
    payload = json.loads(result)
    assert "error" in payload
    assert "didn't catch a location" in payload["error"]
    assert sentinel["called"] is False


@pytest.mark.asyncio
async def test_find_clinician_happy_path_delegates_to_find_clinics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wrapper's contract is "delegate to core.clinician.find_clinics"."""
    from core.config import Settings
    from core.tools import triage as triage_tools

    captured: dict[str, object] = {}

    async def _stub(condition_id: str, location: str, *, settings: object) -> str:
        captured["condition_id"] = condition_id
        captured["location"] = location
        captured["settings"] = settings
        return json.dumps(
            {
                "specialist_label": "physiotherapist or occupational therapist",
                "location_resolved": "Brooklyn",
                "radius_km": 10,
                "results": [],
                "count": 0,
            }
        )

    def _stub_settings() -> Settings:
        return Settings(  # type: ignore[arg-type]
            supabase_url="https://test.supabase.co",
            supabase_publishable_key="test-publishable",
            supabase_jwks_url="https://test.supabase.co/auth/v1/.well-known/jwks.json",
            livekit_url="wss://test.livekit.cloud",
            livekit_api_key="lk-test-key",  # pragma: allowlist secret
            livekit_api_secret="lk-test-secret",  # pragma: allowlist secret
            openai_api_key="sk-test-openai",  # pragma: allowlist secret
            osm_contact_email="ops@example.com",
        )

    monkeypatch.setattr(triage_tools.clinician, "find_clinics", _stub)
    monkeypatch.setattr(triage_tools, "get_settings", _stub_settings)

    result = await dispatch(
        "find_clinician",
        {"condition_id": "carpal_tunnel", "location": "Brooklyn"},
        _ctx(),
    )
    payload = json.loads(result)
    assert "error" not in payload
    assert payload["specialist_label"] == "physiotherapist or occupational therapist"
    assert captured["condition_id"] == "carpal_tunnel"
    assert captured["location"] == "Brooklyn"
