"""Integration-style tests for `agent.session` tool wiring.

The agent registers only the tools in
:data:`agent.session.TRIAGE_TOOL_NAMES` with the realtime model.

The tests below assert the *contract* a LiveKit Agents test harness
would otherwise verify:

* the agent built by :func:`build_agent` exposes only the triage
  allowlist tools,
* the system prompt frames the assistant as an educational triage
  tool, names the in-scope and out-of-scope categories, and instructs
  the model to interview using OPQRST,
* the data-channel topics are distinct from the transcription topic.
"""

from __future__ import annotations

from uuid import UUID

import pytest
import structlog
from agent.session import (
    SYSTEM_PROMPT,
    TOOL_CALLS_TOPIC,
    TRIAGE_TOOL_NAMES,
    _SessionDeps,
    build_agent,
)
from core.auth import User
from core.config import Settings
from core.tools import dispatch
from core.tools.registry import ToolContext


def _deps() -> _SessionDeps:
    return _SessionDeps(
        user=User(id=UUID("11111111-1111-1111-1111-111111111111"), email="alice@example.com"),
        log=structlog.get_logger("test"),
    )


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "supabase_url": "https://test.supabase.co",
        "supabase_publishable_key": "test-publishable",
        "supabase_jwks_url": "https://test.supabase.co/auth/v1/.well-known/jwks.json",
        "livekit_url": "wss://test.livekit.cloud",
        "livekit_api_key": "lk-test-key",  # pragma: allowlist secret
        "livekit_api_secret": "lk-test-secret",  # pragma: allowlist secret
        "openai_api_key": "sk-test-openai",  # pragma: allowlist secret
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_agent_registers_full_triage_allowlist_when_find_clinician_is_enabled() -> None:
    agent = build_agent(_deps(), settings=_settings(osm_contact_email="ops@example.com"))
    registered_names = {t.info.name for t in agent.tools}  # type: ignore[union-attr]
    assert registered_names == set(TRIAGE_TOOL_NAMES)


def test_agent_drops_find_clinician_when_contact_email_is_unset() -> None:
    """No OSM contact email → tool is filtered, prompt branch is omitted."""
    agent = build_agent(_deps(), settings=_settings(osm_contact_email=None))
    registered_names = {t.info.name for t in agent.tools}  # type: ignore[union-attr]
    assert "find_clinician" not in registered_names
    # The other four triage tools still register.
    assert {"record_symptom", "get_differential", "recommend_treatment", "escalate"}.issubset(
        registered_names
    )


def test_record_symptom_is_in_the_triage_allowlist() -> None:
    """Slice 02 introduces the OPQRST `record_symptom` tool."""
    assert "record_symptom" in TRIAGE_TOOL_NAMES


def test_recommend_treatment_and_get_differential_are_in_the_triage_allowlist() -> None:
    """Slice 03 introduces the grounded recommendation tools."""
    assert "recommend_treatment" in TRIAGE_TOOL_NAMES
    assert "get_differential" in TRIAGE_TOOL_NAMES


def test_escalate_is_in_the_triage_allowlist() -> None:
    """Slice 04 introduces the model-callable `escalate` tool."""
    assert "escalate" in TRIAGE_TOOL_NAMES


def test_find_clinician_is_in_the_triage_allowlist() -> None:
    """The clinician-finder feature adds the `find_clinician` tool."""
    assert "find_clinician" in TRIAGE_TOOL_NAMES


def test_system_prompt_advertises_the_safety_floor_and_escalate_tool() -> None:
    """The model must know the server-side screen exists and that
    `escalate` is available for cases the screen does not catch.
    """
    from agent.session import SYSTEM_PROMPT

    lower = SYSTEM_PROMPT.lower()
    assert "escalate" in lower
    assert "red-flag" in lower or "red flag" in lower


def test_system_prompt_forbids_speaking_protocols_not_from_recommend_treatment() -> None:
    """Slice 03's load-bearing prompt rule against numerical hallucination."""
    from agent.session import SYSTEM_PROMPT

    lower = SYSTEM_PROMPT.lower()
    assert "recommend_treatment" in lower
    # The hard rule wording ties spoken protocols/timelines back to the
    # tool. Phrasing variation is fine; the literal "never speak" is
    # what we pin here.
    assert "never speak" in lower


def test_system_prompt_documents_confidence_threshold_for_recommend_treatment() -> None:
    """When the differential's top score is low, the model must defer."""
    from agent.session import SYSTEM_PROMPT

    lower = SYSTEM_PROMPT.lower()
    # The threshold is documented as 0.15 in the prompt. The model has
    # to know the actual number so its decision is deterministic.
    assert "0.15" in lower
    assert "professional evaluation" in lower or "clinician visit" in lower


def test_system_prompt_frames_the_product_as_educational_not_diagnostic() -> None:
    lower = SYSTEM_PROMPT.lower()
    assert "educational" in lower
    assert "not a doctor" in lower
    assert "not a substitute" in lower
    # The prompt should use "may suggest" framing rather than "diagnose".
    assert "may suggest" in lower or "what these symptoms" in lower


def test_system_prompt_names_the_five_in_scope_conditions() -> None:
    lower = SYSTEM_PROMPT.lower()
    assert "carpal tunnel" in lower
    assert "computer vision syndrome" in lower
    assert "tension-type headache" in lower
    # Allow either the formal name or the colloquial "text neck".
    assert "trapezius" in lower or "text neck" in lower
    assert "lumbar" in lower


def test_system_prompt_names_out_of_scope_categories() -> None:
    lower = SYSTEM_PROMPT.lower()
    assert "medication" in lower
    assert "mental health" in lower
    assert "pregnan" in lower
    assert "paediatric" in lower or "pediatric" in lower
    assert "post-surgical" in lower or "postsurgical" in lower


def test_system_prompt_instructs_opqrst_interview() -> None:
    upper = SYSTEM_PROMPT.upper()
    assert "OPQRST" in upper


def test_system_prompt_forbids_inventing_dosages_or_numerical_specifics() -> None:
    lower = SYSTEM_PROMPT.lower()
    assert "never invent" in lower or "do not invent" in lower
    assert "dosage" in lower or "medication" in lower


def test_tool_call_topic_is_distinct_from_transcription() -> None:
    # Frontend listens to two topics; they must not collide.
    assert TOOL_CALLS_TOPIC == "lk.tool-calls"
    assert TOOL_CALLS_TOPIC != "lk.transcription"


@pytest.mark.asyncio
async def test_dispatch_unknown_tool_does_not_raise() -> None:
    deps = _deps()
    ctx = ToolContext(user=deps.user, log=deps.log)
    result = await dispatch("nope", {}, ctx)
    assert isinstance(result, dict)
    assert "error" in result
