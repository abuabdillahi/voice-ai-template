"""Unit tests for :mod:`core.triage`.

The slot store is in-process state — the test fixtures clear it
between tests so cross-test bleed cannot mask isolation bugs.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from core import triage


@pytest.fixture(autouse=True)
def _isolate_state() -> Iterator[None]:
    """Reset the slot store before and after every test."""
    triage._STATES.clear()  # noqa: SLF001 — test-scoped reset
    yield
    triage._STATES.clear()  # noqa: SLF001


# --- slot store ---------------------------------------------------------------


def test_record_symptom_stores_value_under_session_and_slot() -> None:
    state = triage.record_symptom("sess-1", "location", "wrist")
    assert state == {"location": "wrist"}
    assert triage.get_state("sess-1") == {"location": "wrist"}


def test_record_symptom_overwrites_prior_value_for_same_slot() -> None:
    triage.record_symptom("sess-1", "severity", "mild")
    state = triage.record_symptom("sess-1", "severity", "moderate")
    assert state == {"severity": "moderate"}


def test_record_symptom_strips_whitespace_from_value() -> None:
    state = triage.record_symptom("sess-1", "quality", "  tingling  ")
    assert state["quality"] == "tingling"


def test_record_symptom_rejects_unknown_slot() -> None:
    with pytest.raises(ValueError, match="unknown OPQRST slot"):
        triage.record_symptom("sess-1", "marshmallow", "irrelevant")


def test_record_symptom_isolates_state_between_sessions() -> None:
    triage.record_symptom("sess-a", "location", "wrist")
    triage.record_symptom("sess-b", "location", "lower back")
    assert triage.get_state("sess-a") == {"location": "wrist"}
    assert triage.get_state("sess-b") == {"location": "lower back"}


def test_get_state_returns_a_copy() -> None:
    triage.record_symptom("sess-1", "location", "wrist")
    snapshot = triage.get_state("sess-1")
    snapshot["location"] = "mutated"
    assert triage.get_state("sess-1") == {"location": "wrist"}


def test_get_state_for_unknown_session_returns_empty_dict() -> None:
    assert triage.get_state("never-seen") == {}


def test_clear_drops_state_for_one_session_only() -> None:
    triage.record_symptom("sess-a", "location", "wrist")
    triage.record_symptom("sess-b", "location", "lower back")
    triage.clear("sess-a")
    assert triage.get_state("sess-a") == {}
    assert triage.get_state("sess-b") == {"location": "lower back"}


def test_clear_is_a_noop_for_unknown_session() -> None:
    triage.clear("never-seen")  # must not raise


# --- differential ranking -----------------------------------------------------


def test_differential_ranks_carpal_tunnel_above_lumbar_for_wrist_numbness() -> None:
    state = {
        "location": "right wrist",
        "quality": "tingling and numbness in my thumb and fingers",
        "onset": "wakes me up at night",
    }
    ranking = triage.differential(state)
    by_id = dict(ranking)
    assert by_id["carpal_tunnel"] > by_id["lumbar_strain"]


def test_differential_ranks_cvs_above_tension_headache_for_screen_fatigue() -> None:
    state = {
        "location": "behind my eyes",
        "quality": "blurry vision and burning, dry eyes",
        "occupation_context": "staring at the screen for many hours",
    }
    ranking = triage.differential(state)
    by_id = dict(ranking)
    assert by_id["computer_vision_syndrome"] > by_id["tension_type_headache"]


def test_differential_ranks_lumbar_strain_above_carpal_for_seated_back_pain() -> None:
    state = {
        "location": "lower back",
        "aggravators": "long hours sitting in my chair",
        "quality": "stiff and aching",
    }
    ranking = triage.differential(state)
    by_id = dict(ranking)
    assert by_id["lumbar_strain"] > by_id["carpal_tunnel"]


def test_differential_ranks_trapezius_above_carpal_for_neck_shoulder_stiffness() -> None:
    state = {
        "location": "neck and shoulders",
        "quality": "stiff bands across the upper trapezius",
        "occupation_context": "forward-head posture at the screen",
    }
    ranking = triage.differential(state)
    by_id = dict(ranking)
    assert by_id["upper_trapezius_strain"] > by_id["carpal_tunnel"]


def test_differential_returns_zero_scores_for_empty_state() -> None:
    ranking = triage.differential({})
    assert all(score == 0.0 for _, score in ranking)
    # All five conditions still appear so the caller can apply a
    # confidence threshold uniformly.
    ids = {cid for cid, _ in ranking}
    assert ids == {
        "carpal_tunnel",
        "computer_vision_syndrome",
        "tension_type_headache",
        "upper_trapezius_strain",
        "lumbar_strain",
    }


def test_differential_ordering_is_deterministic_for_ties() -> None:
    """Tied scores break by condition id alphabetically — no flakiness."""
    state = {"location": "vague description with no fingerprint hits"}
    ranking_one = triage.differential(state)
    ranking_two = triage.differential(state)
    assert ranking_one == ranking_two
