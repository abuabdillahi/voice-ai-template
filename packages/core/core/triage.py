"""Per-session OPQRST slot store and rule-based differential ranking.

A deep, pure-functional module: the public surface is :func:`record_symptom`,
:func:`get_state`, :func:`clear`, and :func:`differential`. State is
held in-process keyed by session id — slots are derivable from the
persisted transcript if ever needed offline, and storing them
server-side in the database would bypass the ``messages`` table
without buying anything.

Slot vocabulary follows the OPQRST framework a clinician would use:

* ``location`` — where the discomfort is located (the R in OPQRST).
* ``onset`` — when the symptom started.
* ``duration`` — how long it has been present.
* ``quality`` — the qualitative description (aching, sharp, tingling).
* ``severity`` — how intense, how it affects daily activity.
* ``aggravators`` — what makes the symptom worse (the P in OPQRST).
* ``relievers`` — what makes the symptom better (the P in OPQRST).
* ``radiation`` — whether the symptom travels anywhere.
* ``prior_episodes`` — past history of similar symptoms.
* ``occupation_context`` — desk setup, hours at screen, ergonomic context.

The differential ranking is intentionally rule-based for the MVP: each
condition has a fingerprint of canonical keywords, and the score is the
count of fingerprint keywords that appear in the joined slot text. The
seam to swap in a learned ranker later is the function signature
itself — :func:`differential` is the only public ranking surface.
"""

from __future__ import annotations

from threading import Lock

from core.conditions import CONDITIONS

# OPQRST slot names. Surfaced as a tuple so the tool's parameter
# description can list the canonical vocabulary, the frontend slot
# panel can render placeholders for every slot in a stable order, and
# the tests can iterate. Adding a slot is a coordinated change here
# and in the tool's docstring.
SLOT_NAMES: tuple[str, ...] = (
    "location",
    "onset",
    "duration",
    "quality",
    "severity",
    "aggravators",
    "relievers",
    "radiation",
    "prior_episodes",
    "occupation_context",
)

# Module-level state. Keyed by session id; each value is a dict of
# slot-name -> last-recorded-value. A lock guards mutations because the
# agent worker dispatches tool calls on its event loop's executor —
# concurrent calls within the same session are rare but possible (the
# realtime model can issue parallel tool calls), and a lost-update
# under contention would silently drop a slot.
_STATES: dict[str, dict[str, str]] = {}
_STATES_LOCK = Lock()


# Canonical keyword fingerprints per condition. Sourced from the
# condition records' defining symptoms but kept as a separate compact
# list so the differential's matching surface is auditable in one
# place. Adding a condition is a record append in
# :mod:`core.conditions` plus a fingerprint append here.
_FINGERPRINTS: dict[str, tuple[str, ...]] = {
    "carpal_tunnel": (
        "wrist",
        "wrists",
        "thumb",
        "fingers",
        "hand",
        "tingling",
        "numb",
        "numbness",
        "median",
        "keyboard",
        "mouse",
        "night",
        "wakes",
        "wake",
        "pinching",
        "grip",
    ),
    "computer_vision_syndrome": (
        "eye",
        "eyes",
        "vision",
        "blurry",
        "blurred",
        "dry",
        "screen",
        "monitor",
        "blink",
        "burning",
        "tired",
        "glare",
    ),
    "tension_type_headache": (
        "headache",
        "head",
        "temples",
        "forehead",
        "band",
        "pressing",
        "pressure",
        "dull",
        "tight",
    ),
    "upper_trapezius_strain": (
        "neck",
        "shoulder",
        "shoulders",
        "trapezius",
        "stiff",
        "stiffness",
        "posture",
        "forward-head",
        "text neck",
    ),
    "lumbar_strain": (
        "back",
        "lower back",
        "lumbar",
        "sitting",
        "chair",
        "lower-back",
        "spine",
        "hip",
    ),
}


def record_symptom(session_id: str, slot: str, value: str) -> dict[str, str]:
    """Record a slot value for ``session_id`` and return the updated state.

    Unknown slot names are accepted but produce a :class:`ValueError` —
    the realtime model is instructed to use the canonical vocabulary
    in :data:`SLOT_NAMES`, so an unknown slot is a contract bug worth
    surfacing rather than silently storing.

    Empty values are coerced to a stripped string and stored as-is so
    the model can update or correct an earlier disclosure.
    """
    if slot not in SLOT_NAMES:
        raise ValueError(f"unknown OPQRST slot {slot!r}; " f"valid slots: {', '.join(SLOT_NAMES)}")
    cleaned = value.strip()
    with _STATES_LOCK:
        state = _STATES.setdefault(session_id, {})
        state[slot] = cleaned
        return dict(state)


def get_state(session_id: str) -> dict[str, str]:
    """Return a snapshot of the slot state for ``session_id``.

    The returned dict is a copy — callers cannot mutate the live state
    by retaining a reference. Missing sessions return an empty dict.
    """
    with _STATES_LOCK:
        return dict(_STATES.get(session_id, {}))


def clear(session_id: str) -> None:
    """Drop all recorded slots for ``session_id``.

    No-op if the session has no recorded slots. Called at session end
    by the agent worker to keep the in-process map bounded.
    """
    with _STATES_LOCK:
        _STATES.pop(session_id, None)


def differential(state: dict[str, str]) -> list[tuple[str, float]]:
    """Rank conditions by fingerprint-keyword overlap with ``state``.

    For each condition, count fingerprint keywords that appear (as
    substrings, case-insensitive) in the joined slot text. The score is
    that count divided by the fingerprint size, so scores are
    comparable across conditions with different fingerprint widths.

    Ranking is descending by score, breaking ties by condition id for
    determinism. Conditions with score zero are still included so the
    caller can decide whether to apply a confidence threshold.
    """
    blob = " ".join(state.values()).lower()
    ranked: list[tuple[str, float]] = []
    for condition_id, fingerprint in _FINGERPRINTS.items():
        if condition_id not in CONDITIONS:
            # Defensive: the fingerprint table must stay in sync with
            # the condition catalogue. A missing condition is a bug
            # worth surfacing as a zero score rather than crashing.
            continue
        if not blob:
            ranked.append((condition_id, 0.0))
            continue
        matches = sum(1 for keyword in fingerprint if keyword.lower() in blob)
        score = matches / len(fingerprint) if fingerprint else 0.0
        ranked.append((condition_id, score))
    ranked.sort(key=lambda item: (-item[1], item[0]))
    return ranked


__all__ = [
    "SLOT_NAMES",
    "clear",
    "differential",
    "get_state",
    "record_symptom",
]
