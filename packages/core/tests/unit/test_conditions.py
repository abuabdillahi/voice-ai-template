"""Unit tests for :mod:`core.conditions`.

These assert the *shape* of the condition catalogue and the
:func:`kb_for_prompt` round-trip — not the medical *quality* of the
content (a clinician-review concern, deliberately out of scope per the
PRD's testing decisions).
"""

from __future__ import annotations

import pytest
from core.conditions import CONDITIONS, Condition, kb_for_prompt

_EXPECTED_IDS = {
    "carpal_tunnel",
    "computer_vision_syndrome",
    "tension_type_headache",
    "upper_trapezius_strain",
    "lumbar_strain",
}


def test_catalogue_contains_the_five_mvp_conditions() -> None:
    assert set(CONDITIONS.keys()) == _EXPECTED_IDS


def test_each_record_has_the_required_fields_populated() -> None:
    for condition_id, condition in CONDITIONS.items():
        assert isinstance(condition, Condition)
        assert condition.id == condition_id, f"{condition_id} mismatched id field"
        assert condition.name.strip(), f"{condition_id} missing name"
        assert condition.defining_symptoms, f"{condition_id} missing defining_symptoms"
        assert condition.discriminators, f"{condition_id} missing discriminators"
        assert condition.conservative_treatment, f"{condition_id} missing conservative_treatment"
        assert condition.contraindications, f"{condition_id} missing contraindications"
        assert condition.expected_timeline.strip(), f"{condition_id} missing expected_timeline"
        assert condition.red_flags, f"{condition_id} missing red_flags"
        assert condition.sources, f"{condition_id} missing sources"


def test_each_record_carries_at_least_one_source_citation() -> None:
    for condition_id, condition in CONDITIONS.items():
        assert len(condition.sources) >= 1
        for source in condition.sources:
            assert source.strip(), f"{condition_id} has an empty source string"


def test_conditions_are_immutable() -> None:
    """The frozen dataclass should reject attribute assignment."""
    sample = next(iter(CONDITIONS.values()))
    with pytest.raises((AttributeError, TypeError)):
        sample.name = "mutated"  # type: ignore[misc]


def test_kb_for_prompt_emits_one_block_per_condition() -> None:
    prompt = kb_for_prompt()
    for condition in CONDITIONS.values():
        assert f"## {condition.name}" in prompt
        assert f"id: {condition.id}" in prompt


def test_kb_for_prompt_includes_required_section_headers_for_every_record() -> None:
    """Each rendered block must contain the load-bearing sections.

    The model's instructions reference these headers by name, so the
    serialiser keeping them in lockstep with the dataclass is the
    contract under test.
    """
    prompt = kb_for_prompt()
    required_headers = (
        "Defining symptoms:",
        "Conservative treatment:",
        "Condition-specific red flags:",
        "Sources:",
    )
    for header in required_headers:
        # One header occurrence per condition record.
        assert prompt.count(header) == len(CONDITIONS)


def test_kb_for_prompt_includes_each_records_first_defining_symptom() -> None:
    """Round-trip: every record's content lands in the rendered prompt."""
    prompt = kb_for_prompt()
    for condition in CONDITIONS.values():
        assert condition.defining_symptoms[0] in prompt
        assert condition.conservative_treatment[0] in prompt
        assert condition.red_flags[0] in prompt
        assert condition.sources[0] in prompt
        assert condition.expected_timeline in prompt


def test_kb_for_prompt_is_stable_across_invocations() -> None:
    """Pure function: same input → same output. No hidden state."""
    assert kb_for_prompt() == kb_for_prompt()
