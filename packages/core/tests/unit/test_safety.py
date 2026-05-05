"""Unit tests for :mod:`core.safety` regex screen and combiner.

Every tier-1 phrase in the PRD must screen as tier-1; every tier-2
phrase must screen as tier-2; the false-positive negatives below must
not. These are the deterministic floor of the safety pipeline — a
regression here is the worst-case medical-adjacent failure mode the
architecture is designed to prevent.
"""

from __future__ import annotations

import pytest
from core.safety import (
    TIER1_FLAG_IDS,
    TIER2_FLAG_IDS,
    RedFlagResult,
    RedFlagTier,
    combine,
    escalation_script_for,
    regex_screen,
)

# --- tier-1 phrases (every one must screen) -----------------------------------


_TIER1_SAMPLES: dict[str, tuple[str, ...]] = {
    "chest_pain": (
        "I'm having chest pain right now",
        "There's a crushing feeling in my chest",
        "I have tightness in my chest",
    ),
    "worst_headache": (
        "this is the worst headache of my life",
        "my head hit me like a thunderclap",
        "I have a sudden severe headache",
    ),
    "sudden_weakness_or_numbness": (
        "I can't feel my arm",
        "my face is drooping on one side",
        "my arm just went numb",
        "sudden weakness on one side of my body",
    ),
    "loss_of_consciousness": (
        "I passed out earlier",
        "I lost consciousness",
        "I think I blacked out",
    ),
    "sudden_vision_loss": (
        "my vision went black all of a sudden",
        "I suddenly lost my vision in my right eye",
        "I can't see out of my left eye",
    ),
    "difficulty_breathing": (
        "I can't catch my breath",
        "I'm having trouble breathing",
        "I'm gasping for air",
    ),
}


@pytest.mark.parametrize(
    ("flag_id", "utterance"),
    [(flag, sample) for flag, samples in _TIER1_SAMPLES.items() for sample in samples],
)
def test_tier1_phrases_screen_as_emergent(flag_id: str, utterance: str) -> None:
    result = regex_screen(utterance)
    assert result.tier is RedFlagTier.EMERGENT, (flag_id, utterance, result)
    assert flag_id in result.matched_flags
    assert result.source == "regex"


def test_tier1_set_covers_every_required_flag() -> None:
    expected = {
        "chest_pain",
        "worst_headache",
        "sudden_weakness_or_numbness",
        "loss_of_consciousness",
        "sudden_vision_loss",
        "difficulty_breathing",
    }
    assert expected.issubset(set(TIER1_FLAG_IDS))


# --- tier-2 phrases ------------------------------------------------------------


_TIER2_SAMPLES: dict[str, tuple[str, ...]] = {
    "bowel_bladder_with_back_pain": (
        "my back is killing me and I'm losing control of my bladder",
        "back pain and I can't pee",
        "I have back incontinence problems lately",
    ),
    "saddle_anaesthesia": (
        "I'm numb between my legs",
        "saddle numbness has been weird",
        "the inner thigh is numb",
    ),
    "progressive_neurological_deficit": (
        "I'm getting weaker every day",
        "the weakness is spreading down my arm",
    ),
    "fever_with_spinal_pain": (
        "I have a fever and bad back pain",
        "spinal pain with a high temperature",
    ),
    "severe_trauma_history": (
        "I had a bad fall and now my back hurts",
        "a car crash last week",
        "I fell down the stairs onto my neck",
    ),
}


@pytest.mark.parametrize(
    ("flag_id", "utterance"),
    [(flag, sample) for flag, samples in _TIER2_SAMPLES.items() for sample in samples],
)
def test_tier2_phrases_screen_as_urgent(flag_id: str, utterance: str) -> None:
    result = regex_screen(utterance)
    assert result.tier is RedFlagTier.URGENT, (flag_id, utterance, result)
    assert flag_id in result.matched_flags
    assert result.source == "regex"


def test_tier2_set_covers_every_required_flag() -> None:
    expected = {
        "bowel_bladder_with_back_pain",
        "saddle_anaesthesia",
        "progressive_neurological_deficit",
        "fever_with_spinal_pain",
        "severe_trauma_history",
    }
    assert expected.issubset(set(TIER2_FLAG_IDS))


# --- false-positive negatives -------------------------------------------------


@pytest.mark.parametrize(
    "utterance",
    [
        "my chest feels tight from coughing this morning",  # not chest pain
        "I had a bad headache last week but it's gone now",  # past tense
        "my neck is a bit stiff from the screen",  # benign trapezius
        "my wrist tingles a bit when I type",  # not the median-nerve emergency
        "lower back is stiff after long sitting",  # benign lumbar strain
    ],
)
def test_benign_office_strain_phrases_do_not_screen(utterance: str) -> None:
    result = regex_screen(utterance)
    assert result.tier is RedFlagTier.NONE, (utterance, result)
    assert result.matched_flags == ()


# --- combine() precedence -----------------------------------------------------


def test_combine_returns_none_for_no_inputs() -> None:
    result = combine()
    assert result.tier is RedFlagTier.NONE


def test_combine_returns_higher_tier() -> None:
    none_result = RedFlagResult(tier=RedFlagTier.NONE)
    urgent = RedFlagResult(tier=RedFlagTier.URGENT, matched_flags=("saddle_anaesthesia",))
    emergent = RedFlagResult(tier=RedFlagTier.EMERGENT, matched_flags=("chest_pain",))
    assert combine(none_result, urgent).tier is RedFlagTier.URGENT
    assert combine(urgent, emergent).tier is RedFlagTier.EMERGENT
    assert combine(emergent, urgent).tier is RedFlagTier.EMERGENT


def test_combine_unions_matched_flags() -> None:
    a = RedFlagResult(tier=RedFlagTier.URGENT, matched_flags=("a", "b"), source="regex")
    b = RedFlagResult(tier=RedFlagTier.URGENT, matched_flags=("b", "c"), source="classifier")
    result = combine(a, b)
    assert result.matched_flags == ("a", "b", "c")


def test_combine_source_resolves_to_both_when_two_layers_fire() -> None:
    a = RedFlagResult(tier=RedFlagTier.EMERGENT, matched_flags=("chest_pain",), source="regex")
    b = RedFlagResult(
        tier=RedFlagTier.EMERGENT,
        matched_flags=("paraphrase",),
        source="classifier",
    )
    result = combine(a, b)
    assert result.source == "both"


def test_combine_source_resolves_to_single_layer_when_only_one_fires() -> None:
    a = RedFlagResult(tier=RedFlagTier.EMERGENT, matched_flags=("chest_pain",), source="regex")
    b = RedFlagResult(tier=RedFlagTier.NONE, source="classifier")
    result = combine(a, b)
    assert result.source == "regex"


# --- escalation_script_for ----------------------------------------------------


def test_escalation_script_for_each_non_none_tier_is_populated() -> None:
    for tier in (RedFlagTier.EMERGENT, RedFlagTier.URGENT, RedFlagTier.CLINICIAN_SOON):
        script = escalation_script_for(tier)
        assert script.strip()
        assert len(script) > 50  # the wording is the script's whole job


def test_escalation_script_for_emergent_includes_emergency_number_guidance() -> None:
    script = escalation_script_for(RedFlagTier.EMERGENT).lower()
    # Numbers vary by jurisdiction; the script lists the common ones.
    assert "911" in script or "999" in script or "112" in script


def test_escalation_script_for_none_is_empty() -> None:
    assert escalation_script_for(RedFlagTier.NONE) == ""
