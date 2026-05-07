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


def test_each_record_has_a_non_empty_specialist_label() -> None:
    for condition_id, condition in CONDITIONS.items():
        assert condition.specialist_label.strip(), f"{condition_id} missing specialist_label"


def test_each_record_has_at_least_one_specialist_osm_filter() -> None:
    for condition_id, condition in CONDITIONS.items():
        assert isinstance(condition.specialist_osm_filters, tuple)
        assert (
            len(condition.specialist_osm_filters) >= 1
        ), f"{condition_id} missing specialist_osm_filters"


def test_specialist_osm_filters_parse_to_key_equals_value_shape() -> None:
    """Every filter is OSM tag syntax: exactly one ``=`` with non-empty sides."""
    for condition_id, condition in CONDITIONS.items():
        for entry in condition.specialist_osm_filters:
            parts = entry.split("=")
            assert len(parts) == 2, f"{condition_id} filter {entry!r} must contain exactly one '='"
            key, value = parts
            assert key.strip(), f"{condition_id} filter {entry!r} has empty key"
            assert value.strip(), f"{condition_id} filter {entry!r} has empty value"


def test_kb_for_prompt_does_not_render_specialist_referral_metadata() -> None:
    """Referral metadata is for the tool path, not the interview prompt.

    Asserts the new fields' content does not surface in the rendered
    prompt block — the symptom-interview prompt schema must stay
    byte-identical to the pre-clinician-finder baseline.
    """
    prompt = kb_for_prompt()
    for condition in CONDITIONS.values():
        assert (
            condition.specialist_label not in prompt
        ), f"specialist_label for {condition.id} leaked into kb_for_prompt()"
        for entry in condition.specialist_osm_filters:
            assert entry not in prompt, (
                f"specialist_osm_filters entry {entry!r} for "
                f"{condition.id} leaked into kb_for_prompt()"
            )


def test_kb_for_prompt_matches_pre_referral_baseline() -> None:
    """Byte-for-byte regression anchor for the rendered prompt block.

    Captured before the ``specialist_label`` and
    ``specialist_osm_filters`` fields were introduced. If a future
    change to the dataclass or to :func:`kb_for_prompt` legitimately
    needs to alter the prompt, regenerate this fixture intentionally.
    """
    prompt = kb_for_prompt()
    expected = _KB_FOR_PROMPT_BASELINE
    assert prompt == expected


_KB_FOR_PROMPT_BASELINE = "\n\n".join(
    "## {name} (id: {id})\n"
    "\n"
    "Defining symptoms:\n"
    "{defining}\n"
    "\n"
    "Discriminators:\n"
    "{discriminators}\n"
    "\n"
    "Conservative treatment:\n"
    "{treatment}\n"
    "\n"
    "Contraindications:\n"
    "{contraindications}\n"
    "\n"
    "Expected timeline:\n"
    "{timeline}\n"
    "\n"
    "Condition-specific red flags:\n"
    "{red_flags}\n"
    "\n"
    "Sources:\n"
    "{sources}".format(
        id=c.id,
        name=c.name,
        defining="\n".join(f"- {s}" for s in c.defining_symptoms),
        discriminators="\n".join(f"- {s}" for s in c.discriminators),
        treatment="\n".join(f"- {s}" for s in c.conservative_treatment),
        contraindications="\n".join(f"- {s}" for s in c.contraindications),
        timeline=c.expected_timeline,
        red_flags="\n".join(f"- {s}" for s in c.red_flags),
        sources="\n".join(f"- {s}" for s in c.sources),
    )
    for c in CONDITIONS.values()
)
