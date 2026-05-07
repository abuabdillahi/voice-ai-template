"""Unit tests for `recommend_treatment` and `get_differential` tools."""

from __future__ import annotations

import importlib
import json
from collections.abc import Iterator
from uuid import UUID

import pytest
import structlog
from core import triage
from core.auth import User
from core.conditions import CONDITIONS
from core.tools import dispatch, get_tool
from core.tools.registry import ToolContext


@pytest.fixture(autouse=True)
def _ensure_registered() -> Iterator[None]:
    """Reset slot store and re-register triage tools per test.

    `_clear_registry_for_tests` (used by ``test_tools_registry``) wipes
    module-level state; reloading the module triggers ``@tool``
    decoration so the triage tools are present regardless of test
    execution order.
    """
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


# --- recommend_treatment ------------------------------------------------------


def test_recommend_treatment_is_registered() -> None:
    schema = get_tool("recommend_treatment")
    assert schema is not None
    assert "condition_id" in schema.parameters["properties"]


@pytest.mark.asyncio
async def test_recommend_treatment_returns_protocol_for_each_condition() -> None:
    for condition_id in CONDITIONS:
        result = await dispatch("recommend_treatment", {"condition_id": condition_id}, _ctx())
        assert isinstance(result, str)
        payload = json.loads(result)
        assert payload["id"] == condition_id
        # Every protocol field must be populated for every condition —
        # an empty field would let the model speak a hallucinated
        # protocol with empty backing.
        for field in (
            "name",
            "defining_symptoms",
            "discriminators",
            "conservative_treatment",
            "contraindications",
            "expected_timeline",
            "red_flags",
            "sources",
        ):
            assert field in payload, f"{condition_id} missing field {field}"
            value = payload[field]
            if isinstance(value, list):
                assert value, f"{condition_id}.{field} is empty"
            else:
                assert value, f"{condition_id}.{field} is empty"


@pytest.mark.asyncio
async def test_recommend_treatment_unknown_condition_returns_error_string() -> None:
    result = await dispatch(
        "recommend_treatment",
        {"condition_id": "definitely_not_a_condition"},
        _ctx(),
    )
    payload = json.loads(result)
    assert "error" in payload
    assert "definitely_not_a_condition" in payload["error"]
    assert "known_conditions" in payload
    assert set(payload["known_conditions"]) == set(CONDITIONS)


@pytest.mark.asyncio
async def test_recommend_treatment_payload_includes_source_citations() -> None:
    result = await dispatch("recommend_treatment", {"condition_id": "carpal_tunnel"}, _ctx())
    payload = json.loads(result)
    assert isinstance(payload["sources"], list)
    assert len(payload["sources"]) >= 1
    for source in payload["sources"]:
        assert source.strip()


@pytest.mark.asyncio
async def test_recommend_treatment_strips_referral_metadata_from_payload() -> None:
    """Referral fields stay out of the realtime model's read-back payload.

    ``specialist_label`` and ``specialist_osm_filters`` are inputs to
    the ``find_clinician`` tool path. Forwarding them through
    ``recommend_treatment`` surfaces clinic-adjacent strings to the
    realtime model, which then trips on the unsourced-clinician-names
    hard rule and stops speaking after the tool returns. Pin the
    contract: the wire payload contains the symptom-interview fields
    only.
    """
    for condition_id in CONDITIONS:
        result = await dispatch("recommend_treatment", {"condition_id": condition_id}, _ctx())
        payload = json.loads(result)
        assert "specialist_label" not in payload, f"{condition_id} payload leaked specialist_label"
        assert (
            "specialist_osm_filters" not in payload
        ), f"{condition_id} payload leaked specialist_osm_filters"


# --- get_differential ---------------------------------------------------------


def test_get_differential_is_registered() -> None:
    schema = get_tool("get_differential")
    assert schema is not None


@pytest.mark.asyncio
async def test_get_differential_with_carpal_tunnel_state_ranks_carpal_tunnel_top() -> None:
    triage.record_symptom("sess-1", "location", "right wrist")
    triage.record_symptom("sess-1", "quality", "tingling and numbness in my thumb and fingers")
    triage.record_symptom("sess-1", "onset", "wakes me up at night")

    result = await dispatch("get_differential", {}, _ctx())
    payload = json.loads(result)
    assert payload["ranking"][0]["condition_id"] == "carpal_tunnel"
    assert payload["ranking"][0]["score"] > 0
    assert payload["threshold"] > 0


@pytest.mark.asyncio
async def test_get_differential_with_low_signal_state_returns_low_top_score() -> None:
    triage.record_symptom("sess-1", "location", "I feel a bit off")
    result = await dispatch("get_differential", {}, _ctx())
    payload = json.loads(result)
    # The threshold rule lives in `_THRESHOLD`; confirm an ambiguous
    # state's top score is below it so the model is instructed to
    # recommend professional evaluation rather than a treatment.
    assert payload["ranking"][0]["score"] < payload["threshold"]


@pytest.mark.asyncio
async def test_get_differential_without_session_id_returns_error() -> None:
    ctx = ToolContext(
        user=User(id=UUID("11111111-1111-1111-1111-111111111111"), email="a@b"),
        log=structlog.get_logger("test"),
        session_id="",
    )
    result = await dispatch("get_differential", {}, ctx)
    payload = json.loads(result)
    assert "error" in payload
    assert payload["ranking"] == []
