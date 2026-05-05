"""Triage tools — model-callable surface for the OPQRST interview.

The realtime model calls these tools to write into the per-session slot
store maintained by :mod:`core.triage`, look up the current
differential, and read the grounded treatment protocol for a chosen
condition. The slot store is what makes the otherwise-invisible
interview backbone visible: the agent worker forwards the slot state
to the frontend so the user can see what the agent has gathered.

Tools registered here:

* :func:`record_symptom` (slice 02) — write one OPQRST slot.
* :func:`get_differential` (slice 03) — read the ranked condition list
  given the current slot state.
* :func:`recommend_treatment` (slice 03) — return the conservative
  protocol for a condition. The model is instructed (via the system
  prompt) never to speak a protocol that did not come from this tool.
* slice 04 will add ``escalate`` to the same module.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from core import safety, triage
from core.conditions import CONDITIONS
from core.tools.registry import ToolContext, tool

# Confidence threshold for `recommend_treatment`. The system prompt
# tells the model to recommend professional evaluation rather than
# calling the tool when the top differential score is below this
# threshold. Surfaced as a module-level constant so the prompt language
# and the dispatch-time guard share one source of truth.
RECOMMEND_TREATMENT_CONFIDENCE_THRESHOLD = 0.15

# Surfaced as a module constant so the tool description and the
# system-prompt language can stay in lockstep. The tool's docstring is
# what the realtime model receives as its parameter help.
_SLOT_VOCAB_HINT = ", ".join(triage.SLOT_NAMES)


@tool(
    name="record_symptom",
    description=(
        "Record one OPQRST slot for the current symptom interview. Call this "
        "every time the user discloses a new piece of information — one call "
        "per slot per disclosure. Use the canonical slot vocabulary: "
        f"{_SLOT_VOCAB_HINT}. The 'value' is a short phrase capturing what the "
        "user said. Returns a JSON snapshot of the slot state so far."
    ),
)
async def record_symptom(ctx: ToolContext, slot: str, value: str) -> str:
    """Record an OPQRST slot value for the current session.

    The realtime model calls this whenever the user volunteers
    information that fits one of the OPQRST slots — e.g. "my wrist
    started tingling last Wednesday" produces two calls
    (``location='wrist'``, ``onset='last Wednesday'``).

    Returns a JSON-encoded snapshot of the full slot state so the model
    can reason about what is still missing without calling a separate
    "what do you have so far" tool.
    """
    if not ctx.session_id:
        ctx.log.warning("record_symptom.no_session_id")
        return json.dumps({"error": "session id is missing", "state": {}})
    try:
        state = triage.record_symptom(ctx.session_id, slot, value)
    except ValueError as exc:
        ctx.log.warning("record_symptom.invalid_slot", error=str(exc))
        return json.dumps({"error": str(exc), "state": triage.get_state(ctx.session_id)})
    ctx.log.info("record_symptom.recorded", slot=slot, slots_filled=len(state))
    return json.dumps({"state": state})


@tool(
    name="get_differential",
    description=(
        "Return the current ranked list of candidate conditions given the "
        "OPQRST slots gathered so far. Call this before deciding which "
        "condition_id to pass to `recommend_treatment`. Returns a JSON list "
        "of (condition_id, score) pairs ordered by score descending; an "
        "empty slot state returns zero scores for every condition."
    ),
)
async def get_differential(ctx: ToolContext) -> str:
    """Expose the rule-based differential ranking to the realtime model.

    Choosing a tool over a system-prompt seed (the slice's design seam)
    keeps the ranking *current* — every call reflects the slots
    disclosed up to that turn rather than a frozen session-start
    snapshot. The seam to swap in a learned ranker later remains
    :func:`core.triage.differential`.
    """
    if not ctx.session_id:
        ctx.log.warning("get_differential.no_session_id")
        return json.dumps({"error": "session id is missing", "ranking": []})
    state = triage.get_state(ctx.session_id)
    ranking = triage.differential(state)
    ctx.log.info(
        "get_differential.ranked",
        slots_filled=len(state),
        top_id=ranking[0][0] if ranking else None,
        top_score=ranking[0][1] if ranking else 0.0,
    )
    return json.dumps(
        {
            "ranking": [{"condition_id": cid, "score": score} for cid, score in ranking],
            "threshold": RECOMMEND_TREATMENT_CONFIDENCE_THRESHOLD,
        }
    )


@tool(
    name="recommend_treatment",
    description=(
        "Return the conservative treatment protocol for a condition. The "
        "condition_id must match one of the ids in the embedded knowledge "
        "base. Use this whenever you are about to speak a treatment, "
        "stretch duration, exercise rep count, contraindication, or "
        "expected timeline — never speak any of those from your own "
        "knowledge. Returns a JSON object with the protocol fields."
    ),
)
async def recommend_treatment(ctx: ToolContext, condition_id: str) -> str:
    """Return the conservative-treatment block for ``condition_id``.

    Validates the id against :data:`core.conditions.CONDITIONS` and
    returns a structured payload (conservative treatment,
    contraindications, expected timeline, condition-specific red
    flags, source citations). An unknown id returns a verbalisable
    error string rather than raising — the realtime model can
    apologise and ask a clarifying question.
    """
    condition = CONDITIONS.get(condition_id)
    if condition is None:
        ctx.log.warning("recommend_treatment.unknown_condition", condition_id=condition_id)
        return json.dumps(
            {
                "error": (
                    f"I don't have a protocol for {condition_id!r}. "
                    f"In-scope conditions are: {', '.join(sorted(CONDITIONS))}."
                ),
                "known_conditions": sorted(CONDITIONS),
            }
        )

    payload = asdict(condition)
    # Convert tuples to lists so the JSON wire shape is stable across
    # downstream consumers that round-trip through standard JSON.
    for key, value in payload.items():
        if isinstance(value, tuple):
            payload[key] = list(value)
    ctx.log.info("recommend_treatment.returned", condition_id=condition_id)
    return json.dumps(payload)


@tool(
    name="escalate",
    description=(
        "Stop the symptom interview and escalate to professional care. Call "
        "this when the user volunteers a red-flag symptom you judge worth "
        "escalating, or when you cannot continue safely. The 'tier' must be "
        "one of 'emergent' (call emergency services now), 'urgent' (urgent "
        "care today), or 'clinician_soon' (clinician evaluation this week). "
        "The 'reason' is a one-sentence summary of why. The agent worker "
        "plays the scripted escalation message and ends the session — your "
        "spoken reply should mirror that script rather than re-paraphrasing."
    ),
)
async def escalate(ctx: ToolContext, tier: str, reason: str) -> str:
    """Model-callable escalation tool.

    The realtime model can volunteer this call when it judges
    escalation is warranted (the parallel server-side regex+classifier
    pipeline does *not* depend on the model doing so — see
    :mod:`core.safety` and the agent's ``_wire_safety_screen`` hook).
    Returns the scripted message so the model has the exact wording to
    speak; the agent worker also plays the script via ``session.say``
    when it sees this tool fire so the spoken output is anchored to the
    versioned script even if the model paraphrases.
    """
    try:
        normalised = safety.RedFlagTier(tier)
    except ValueError:
        ctx.log.warning("escalate.invalid_tier", tier=tier)
        return json.dumps(
            {
                "error": (
                    f"unknown escalation tier {tier!r}; "
                    "valid tiers: emergent, urgent, clinician_soon"
                )
            }
        )
    script = safety.escalation_script_for(normalised)
    ctx.log.info("escalate.invoked", tier=normalised.value, reason=reason)
    return json.dumps(
        {
            "tier": normalised.value,
            "script": script,
            "reason": reason,
        }
    )


__all__ = [
    "RECOMMEND_TREATMENT_CONFIDENCE_THRESHOLD",
    "escalate",
    "get_differential",
    "recommend_treatment",
    "record_symptom",
]
