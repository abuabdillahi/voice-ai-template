"""Defence-in-depth red-flag detector.

A deep, pure-functional module for the safety floor. The public surface
is the :class:`RedFlagTier` enum, the :class:`RedFlagResult` payload,
:func:`regex_screen` (synchronous, deterministic), :func:`combine` (the
"highest tier wins" precedence rule), and :func:`escalation_script_for`
(the spoken text per tier, sourced from a single versioned constant).

Design choice — the screen runs server-side, **independently of the
realtime model**, on every committed user utterance. It is *not*
exposed as a model-callable tool: making the detector something the
model chooses whether to call is the failure mode the architecture is
built to prevent. The model can still volunteer an :func:`escalate`
call when it judges escalation is warranted (slice 04 adds that tool),
but the parallel regex-and-classifier pipeline does not depend on the
model doing so.

Slice 04 implements the regex layer here. Slice 06 adds
:func:`classify` (gpt-4o-mini async classifier with structured
output) to the same module; the agent worker fires both in parallel
and votes via :func:`combine`.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from openai.types.chat import ChatCompletionMessageParam
    from openai.types.shared_params import ResponseFormatJSONSchema

from core.config import Settings, get_settings

_log = logging.getLogger(__name__)


class RedFlagTier(StrEnum):
    """Severity tiers for the red-flag detector.

    The string values are persisted on the ``safety_events`` table
    (slice 05) — the value/name pair is part of the schema contract.

    * ``emergent`` — call emergency services immediately.
    * ``urgent`` — go to urgent care today.
    * ``clinician_soon`` — schedule a clinician evaluation this week.
    * ``none`` — no red flag detected; the screen is silent.
    """

    EMERGENT = "emergent"
    URGENT = "urgent"
    CLINICIAN_SOON = "clinician_soon"
    NONE = "none"


# Tier ordering used by :func:`combine` — higher index wins.
_TIER_ORDER: tuple[RedFlagTier, ...] = (
    RedFlagTier.NONE,
    RedFlagTier.CLINICIAN_SOON,
    RedFlagTier.URGENT,
    RedFlagTier.EMERGENT,
)


@dataclass(frozen=True, slots=True)
class RedFlagResult:
    """Outcome of one red-flag screening pass.

    ``matched_flags`` lists the canonical phrase ids that fired (e.g.
    ``"chest_pain"``, ``"worst_headache"``). They are the audit
    record persisted to ``safety_events`` (slice 05) and they
    parameterise the escalation log line.

    ``source`` records which layer produced the result —
    ``"regex"`` for slice 04, ``"classifier"`` once slice 06 lands,
    and ``"both"`` when :func:`combine` unions hits from both layers.
    """

    tier: RedFlagTier
    matched_flags: tuple[str, ...] = field(default_factory=tuple)
    source: str = "regex"


# ---------------------------------------------------------------------------
# Phrase list — single editable constant per tier.
# ---------------------------------------------------------------------------
# Each entry pairs a canonical phrase id with a list of regex patterns.
# Patterns are compiled with ``re.IGNORECASE`` and matched against the
# committed user utterance. The patterns intentionally hold paraphrases
# inline rather than relying on token-level fuzz — the regex layer is
# the deterministic floor, the classifier (slice 06) catches semantic
# paraphrases the regex cannot.
#
# Sources for the tier-1 set: NHS "When to call 999" guidance and
# AHA/AAN stroke-symptom protocols. The tier-2 cauda-equina markers
# are sourced from NICE NG59 (low back pain and sciatica). Each
# inline comment names the authoritative source.

_TIER1_PHRASES: dict[str, tuple[str, ...]] = {
    # NHS / AHA — chest pain is the canonical "call 999 now" trigger.
    # Patterns are deliberately narrow: "chest feels tight from
    # coughing" is benign and must not trigger this flag (see the
    # false-positive-negatives test suite).
    "chest_pain": (
        r"\bchest pain\b",
        r"\bpain in (my|the) chest\b",
        r"\bcrushing.*chest\b",
        r"\bchest.*crushing\b",
        r"\btightness in (my )?chest\b",
        r"\b(my )?chest tightness\b",
        r"\b(my )?chest is tight(ening)?\b(?!.*\b(coughing|cough|cold|flu)\b)",
    ),
    # ICHD-3 / AAN — "thunderclap" / "worst of my life" headache markers.
    "worst_headache": (
        r"\bworst headache\b",
        r"\bworst.*headache.*(of|in).*(my )?life\b",
        r"\bthunder ?clap\b",
        r"\bsudden.*severe headache\b",
        r"\bheadache.*(came|hit) on (sudden(ly)?|like)\b",
    ),
    # AHA stroke protocol — sudden one-sided weakness or numbness.
    "sudden_weakness_or_numbness": (
        r"\bcan'?t (feel|move) (my )?(arm|leg|face|side)\b",
        r"\bsudden(ly)?.*(weak(ness)?|numb(ness)?).*(arm|leg|face|side|one[- ]sided)\b",
        r"\bone[- ]sided (weak(ness)?|numb(ness)?)\b",
        r"\bface.*droop(ing|ed|s)?\b",
        r"\bmy (arm|leg) (just )?went numb\b",
    ),
    # NHS — loss of consciousness / fainting episode.
    "loss_of_consciousness": (
        r"\bpassed out\b",
        r"\blost consciousness\b",
        r"\bfainted\b",
        r"\bblack(ed)? out\b",
    ),
    # AAO — sudden vision loss is an ophthalmologic emergency.
    "sudden_vision_loss": (
        r"\bsudden(ly)?.*(lost|loss of) (my )?vision\b",
        r"\bvision (just )?went black\b",
        r"\bcan'?t see (out of |from )?(my )?(eye|right|left)\b",
        r"\b(suddenly|all at once).*blind\b",
    ),
    # NHS — difficulty breathing / shortness of breath at rest.
    "difficulty_breathing": (
        r"\bcan'?t (catch my )?breathe?\b",
        r"\b(trouble|difficulty) breathing\b",
        r"\bshort(ness)? of breath\b",
        r"\bgasping for (air|breath)\b",
    ),
}

_TIER2_PHRASES: dict[str, tuple[str, ...]] = {
    # NICE NG59 — cauda equina markers: bowel/bladder dysfunction with
    # back pain. Saddle anaesthesia handled by the next entry.
    "bowel_bladder_with_back_pain": (
        r"\b(losing|lost|loss of) (control of )?(my )?(bowel|bladder)\b",
        r"\bcan'?t (control )?(my )?(bowels?|bladder)\b",
        r"\bincontinen(ce|t)\b.*\bback\b",
        r"\bback\b.*\bincontinen(ce|t)\b",
        r"\bback pain\b.*\bcan'?t (pee|urinate|wee)\b",
    ),
    # NICE NG59 — saddle anaesthesia is the cauda-equina specific marker.
    "saddle_anaesthesia": (
        r"\bnumb.*(saddle|between (my )?legs|groin|inner thigh)\b",
        r"\b(saddle|between (my )?legs|groin|inner thigh).*numb\b",
        r"\bsaddle (anaesthesia|anesthesia|numbness)\b",
    ),
    # NICE — progressive neurological deficit: increasing weakness over time.
    "progressive_neurological_deficit": (
        r"\b(getting|growing) weaker.*(every day|each day|over time)\b",
        r"\bprogressively\b.*\bweak(er)?\b",
        r"\b(weakness|numbness) (is )?spreading\b",
    ),
    # NICE — fever with spinal pain (potential discitis / abscess).
    "fever_with_spinal_pain": (
        r"\bfever\b.*\b(back|spine|spinal|neck) pain\b",
        r"\b(back|spine|spinal|neck) pain\b.*\bfever\b",
        r"\bhigh temperature\b.*\b(back|spine|neck)\b",
        r"\b(back|spine|spinal|neck) pain\b.*\bhigh temperature\b",
        r"\b(spinal|back) pain\b.*\b(fever|high temperature)\b",
        r"\b(fever|high temperature)\b.*\b(spinal|back) pain\b",
    ),
    # AAOS — severe trauma history changes the triage tier.
    "severe_trauma_history": (
        r"\bbad (fall|crash|accident)\b.*\b(back|neck|head)\b",
        r"\bcar (crash|accident)\b",
        r"\bfell (down|off|from).*(stairs|ladder|height)\b",
    ),
}


_COMPILED_TIER1: dict[str, tuple[re.Pattern[str], ...]] = {
    flag_id: tuple(re.compile(pat, re.IGNORECASE) for pat in patterns)
    for flag_id, patterns in _TIER1_PHRASES.items()
}
_COMPILED_TIER2: dict[str, tuple[re.Pattern[str], ...]] = {
    flag_id: tuple(re.compile(pat, re.IGNORECASE) for pat in patterns)
    for flag_id, patterns in _TIER2_PHRASES.items()
}


# ---------------------------------------------------------------------------
# Escalation scripts — single editable constant referenced from one place.
# ---------------------------------------------------------------------------
# Used by both the system prompt (the model is instructed never to deviate
# from the scripted text) and the runtime escalation hook
# (`_wire_safety_screen` plays the script via `session.say`). Keeping the
# wording in one place means a single edit changes the spoken output and
# the prompt-side reference together.

_ESCALATION_SCRIPTS: dict[RedFlagTier, str] = {
    RedFlagTier.EMERGENT: (
        "What you're describing could be a medical emergency. Please stop our "
        "conversation now and call your local emergency number — 911 in the US, "
        "999 in the UK, or 112 in much of Europe. If you can't make the call "
        "yourself, ask someone nearby to do it. I'm an educational tool and I "
        "can't help you with this. Please go now."
    ),
    RedFlagTier.URGENT: (
        "What you're describing needs to be looked at urgently — today, not "
        "next week. Please go to urgent care or your nearest emergency "
        "department. If you can, ask someone to come with you. I'm an "
        "educational tool and this is outside what I can help you with."
    ),
    RedFlagTier.CLINICIAN_SOON: (
        "What you're describing should be evaluated by a clinician this week. "
        "Please book an appointment with your GP or a primary-care provider "
        "and bring along the symptoms we have talked through. I'm not the "
        "right tool to manage this on its own."
    ),
    RedFlagTier.NONE: "",
}


# ---------------------------------------------------------------------------
# Public functions.
# ---------------------------------------------------------------------------


def regex_screen(utterance: str) -> RedFlagResult:
    """Screen ``utterance`` against the curated phrase list.

    Pure function. Sub-millisecond. The phrase list is the deterministic
    floor for the safety pipeline — every tier-1 phrase listed in the
    PRD must screen as tier-1 here. Returns
    ``RedFlagResult(tier=NONE, matched_flags=(), source="regex")`` when
    no phrase matches.

    Tier-1 always wins over tier-2 within this single call: if both
    sets fire, the result reports the union of matched flags but the
    higher tier. (Most realistic utterances will only match one set.)
    """
    text = utterance or ""
    tier1_hits: list[str] = []
    tier2_hits: list[str] = []
    for flag_id, patterns in _COMPILED_TIER1.items():
        if any(p.search(text) for p in patterns):
            tier1_hits.append(flag_id)
    for flag_id, patterns in _COMPILED_TIER2.items():
        if any(p.search(text) for p in patterns):
            tier2_hits.append(flag_id)
    if tier1_hits:
        return RedFlagResult(
            tier=RedFlagTier.EMERGENT,
            matched_flags=tuple(tier1_hits + tier2_hits),
            source="regex",
        )
    if tier2_hits:
        return RedFlagResult(
            tier=RedFlagTier.URGENT,
            matched_flags=tuple(tier2_hits),
            source="regex",
        )
    return RedFlagResult(tier=RedFlagTier.NONE, matched_flags=(), source="regex")


def combine(*results: RedFlagResult) -> RedFlagResult:
    """Vote across screening results — highest tier wins.

    The ``source`` field is set to ``"regex"`` if only the regex layer
    fired, ``"classifier"`` if only the classifier fired, and
    ``"both"`` when both layers produced a non-NONE result. The matched
    flags are the union across all inputs (de-duplicated, order
    preserved by first occurrence).

    With no inputs, returns a NONE result so callers do not have to
    special-case an empty list.
    """
    if not results:
        return RedFlagResult(tier=RedFlagTier.NONE)

    winning = max(results, key=lambda r: _TIER_ORDER.index(r.tier))

    nonzero_sources = {r.source for r in results if r.tier is not RedFlagTier.NONE}
    if len(nonzero_sources) > 1:
        source = "both"
    elif len(nonzero_sources) == 1:
        source = next(iter(nonzero_sources))
    else:
        source = winning.source

    seen: set[str] = set()
    flags: list[str] = []
    for r in results:
        for flag in r.matched_flags:
            if flag not in seen:
                seen.add(flag)
                flags.append(flag)

    return RedFlagResult(tier=winning.tier, matched_flags=tuple(flags), source=source)


def escalation_script_for(tier: RedFlagTier) -> str:
    """Return the spoken escalation script for ``tier``.

    Single-source-of-truth lookup. Edits to the wording only need to
    happen in :data:`_ESCALATION_SCRIPTS` — both the system prompt and
    the runtime ``session.say`` path read from here.
    """
    return _ESCALATION_SCRIPTS.get(tier, "")


# Public list of tier-1 / tier-2 flag ids — for tests and docs that want
# to enumerate the phrase coverage without reaching into the compiled
# regex tables.
TIER1_FLAG_IDS: tuple[str, ...] = tuple(_TIER1_PHRASES.keys())
TIER2_FLAG_IDS: tuple[str, ...] = tuple(_TIER2_PHRASES.keys())


# ---------------------------------------------------------------------------
# Layer 2 — gpt-4o-mini classifier (slice 06).
# ---------------------------------------------------------------------------

CLASSIFIER_SYSTEM_PROMPT = """\
You are a triage safety classifier. You read one user utterance from a voice triage conversation and decide whether it contains a medical red flag that warrants immediate escalation. You never converse with the user — you return a structured judgement.

Tiers:
- "emergent": the user is describing a possible medical emergency that warrants calling emergency services immediately. Examples: chest pain or chest tightness suggesting cardiac involvement, sudden severe headache (thunderclap), sudden one-sided weakness or numbness, loss of consciousness, sudden vision loss in one eye, difficulty breathing at rest, signs of stroke (FAST), severe allergic reaction with airway involvement.
- "urgent": the user is describing a presentation that warrants urgent in-person evaluation today. Examples: cauda equina markers (bowel or bladder dysfunction with back pain, saddle anaesthesia, progressive lower-extremity weakness), fever with spinal pain, severe trauma history affecting the spine or head, progressive neurological deficit.
- "clinician_soon": the user is describing a presentation that warrants a clinician evaluation this week (not today). Examples: persistent symptoms over six weeks, worsening symptoms not explained by ergonomics, sustained sleep disruption from pain.
- "none": the user is describing routine office strain — wrist tingling from typing, neck stiffness from screen time, lower back stiffness from sitting, eye strain — without any of the above red-flag markers.

You return JSON matching the schema. The matched_flags array names short canonical ids for any red-flag categories you saw, e.g. "chest_pain", "sudden_weakness", "saddle_anaesthesia". Use lowercase snake_case ids; the registry doesn't enforce a fixed set, but use ids consistent with the examples above.

Bias toward escalation when uncertain. A false-positive escalation costs the user a clinician visit; a false-negative costs them a missed emergency. Pick the higher tier when in doubt.
"""

_CLASSIFIER_RESPONSE_SCHEMA: dict[str, Any] = {
    "name": "red_flag_classification",
    "schema": {
        "type": "object",
        "properties": {
            "tier": {
                "type": "string",
                "enum": ["emergent", "urgent", "clinician_soon", "none"],
            },
            "matched_flags": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["tier", "matched_flags"],
        "additionalProperties": False,
    },
    "strict": True,
}


async def classify(
    utterance: str,
    *,
    settings: Settings | None = None,
) -> RedFlagResult:
    """Classify ``utterance`` with the gpt-4o-mini layer.

    Async because the agent worker fires regex and classifier in
    parallel via :func:`asyncio.gather` (see slice 06's
    ``_wire_safety_screen`` rewrite). Failure modes — timeout, API
    error, malformed structured output — return a NONE-tier result
    with a logged warning rather than raising. The regex floor still
    fires on the same utterance, so a classifier outage degrades the
    pipeline to its slice-04 behaviour rather than tearing down the
    voice loop.

    The model id is read from :class:`Settings.safety_classifier_model`
    so a future safety-quality upgrade is one config change.
    """
    text = (utterance or "").strip()
    if not text:
        return RedFlagResult(tier=RedFlagTier.NONE, source="classifier")

    resolved_settings = settings or get_settings()

    try:
        from openai import AsyncOpenAI
    except ImportError:  # pragma: no cover — openai is installed via livekit-agents extra
        _log.warning("safety.classify.openai_import_failed")
        return RedFlagResult(tier=RedFlagTier.NONE, source="classifier")

    client = AsyncOpenAI(api_key=resolved_settings.openai_api_key)
    messages = cast(
        "list[ChatCompletionMessageParam]",
        [
            {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
    )
    response_format = cast(
        "ResponseFormatJSONSchema",
        {"type": "json_schema", "json_schema": _CLASSIFIER_RESPONSE_SCHEMA},
    )
    try:
        response = await client.chat.completions.create(
            model=resolved_settings.safety_classifier_model,
            messages=messages,
            response_format=response_format,
            max_tokens=120,
            temperature=0.0,
        )
    except Exception as exc:  # noqa: BLE001 — best-effort classifier
        _log.warning("safety.classify.api_error", extra={"error": str(exc)})
        return RedFlagResult(tier=RedFlagTier.NONE, source="classifier")

    choice = response.choices[0] if response.choices else None
    raw = choice.message.content if choice and choice.message else None
    if not raw:
        _log.warning("safety.classify.empty_response")
        return RedFlagResult(tier=RedFlagTier.NONE, source="classifier")

    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        _log.warning("safety.classify.malformed_response", extra={"error": str(exc), "raw": raw})
        return RedFlagResult(tier=RedFlagTier.NONE, source="classifier")

    tier_value = decoded.get("tier")
    matched_flags = decoded.get("matched_flags") or []
    try:
        tier = RedFlagTier(tier_value)
    except ValueError:
        _log.warning("safety.classify.unknown_tier", extra={"tier": tier_value})
        return RedFlagResult(tier=RedFlagTier.NONE, source="classifier")

    flags = tuple(str(f) for f in matched_flags if isinstance(f, str | int))
    return RedFlagResult(tier=tier, matched_flags=flags, source="classifier")


__all__ = [
    "CLASSIFIER_SYSTEM_PROMPT",
    "TIER1_FLAG_IDS",
    "TIER2_FLAG_IDS",
    "RedFlagResult",
    "RedFlagTier",
    "classify",
    "combine",
    "escalation_script_for",
    "regex_screen",
]
