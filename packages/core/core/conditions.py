"""Condition knowledge base for the office-strain triage product.

A pure-data module: five condition records typed as :class:`Condition`,
exposed as ``CONDITIONS`` keyed by a snake_case condition id, plus a
:func:`kb_for_prompt` helper that renders the catalogue into a stable,
parseable block embedded in the realtime model's system prompt at
session start.

Adding a sixth condition is a single record append below — the helper
serialises every record the same way, so no glue code changes. The
catalogue boundary (this module's exported surface) is the seam to
swap to retrieval-augmented grounding once the catalogue grows past
roughly ten conditions; until then, in-prompt embedding is faster to
debug and eliminates a class of retrieval-induced hallucination.

Sources are public clinical guidance — NIOSH, OSHA, AAOS, and
physiotherapy association protocols — cited inline on every record so
a clinician reviewer can audit the content without leaving the file.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Condition:
    """One office-strain condition the triage agent can reason about.

    The shape is intentionally flat. Every field is required. The
    interview-relevant fields render into the system-prompt block via
    :func:`kb_for_prompt`; the referral-metadata fields
    (``specialist_label``, ``specialist_osm_filters``) are read by the
    ``find_clinician`` tool path and deliberately do not bleed into the
    symptom-interview prompt. Adding a new prompt-rendered field is a
    coordinated change across :func:`kb_for_prompt` and the realtime
    prompt's instruction language; refusing optional fields keeps the
    prompt schema stable across record additions.
    """

    id: str
    name: str
    defining_symptoms: tuple[str, ...]
    discriminators: tuple[str, ...]
    conservative_treatment: tuple[str, ...]
    contraindications: tuple[str, ...]
    expected_timeline: str
    red_flags: tuple[str, ...]
    sources: tuple[str, ...]
    specialist_label: str
    specialist_osm_filters: tuple[str, ...]


CONDITIONS: dict[str, Condition] = {
    "carpal_tunnel": Condition(
        id="carpal_tunnel",
        name="Carpal tunnel syndrome",
        defining_symptoms=(
            "Numbness or tingling in the thumb, index, middle, and radial half of the ring finger",
            "Worse at night or on waking",
            "Aggravated by sustained wrist flexion or repetitive keyboard or mouse use",
            "Hand may feel weak when gripping or pinching small objects",
        ),
        discriminators=(
            "Symptoms follow the median nerve distribution (sparing the little finger)",
            "Shaking the hand often relieves the tingling — the 'flick sign'",
            "Symptoms typically wake the user from sleep, distinguishing from positional ulnar issues",
        ),
        conservative_treatment=(
            "Neutral-wrist splinting at night for several weeks",
            "Ergonomic adjustment of keyboard, mouse, and chair height to keep wrists neutral",
            "Frequent micro-breaks; gentle median-nerve gliding exercises during the workday",
            "Reduce repetitive wrist-flexion loads where possible",
        ),
        contraindications=(
            "Avoid forceful wrist stretching that reproduces the tingling",
            "Do not continue heavy gripping work through worsening numbness",
        ),
        expected_timeline=(
            "Many users report improvement within four to six weeks of consistent splinting "
            "and ergonomic change. Symptoms persisting beyond six weeks warrant a clinician visit."
        ),
        red_flags=(
            "Hand or thenar muscle wasting",
            "Persistent numbness that does not vary with activity",
            "Sudden severe weakness in the hand",
        ),
        sources=(
            "AAOS OrthoInfo — Carpal Tunnel Syndrome (orthoinfo.aaos.org)",
            "NIOSH — Musculoskeletal Disorders and Workplace Factors",
        ),
        specialist_label="physiotherapist or occupational therapist",
        specialist_osm_filters=(
            "healthcare=physiotherapist",
            "healthcare=occupational_therapist",
        ),
    ),
    "computer_vision_syndrome": Condition(
        id="computer_vision_syndrome",
        name="Computer vision syndrome (digital eye strain)",
        defining_symptoms=(
            "Eye strain, tired or burning eyes after prolonged screen use",
            "Blurred or double vision late in the workday",
            "Dry, irritated eyes; reduced blink rate during screen tasks",
            "Headache around the brow or temples that resolves away from the screen",
        ),
        discriminators=(
            "Symptoms correlate tightly with hours of near-screen work and resolve with breaks",
            "No fixed visual deficit — vision is normal at distance after a rest",
            "Distinguished from migraine by the absence of nausea, photophobia, or aura",
        ),
        conservative_treatment=(
            "Apply the 20-20-20 rule: every 20 minutes look at something about 20 feet away for 20 seconds",
            "Adjust screen distance to about an arm's length and position the top of the screen at or below eye level",
            "Reduce glare; balance ambient lighting with screen brightness",
            "Use lubricating eye drops if dryness is prominent; consciously blink more during screen work",
            "Have an up-to-date eye exam; consider computer-specific lenses if a refractive correction is overdue",
        ),
        contraindications=(
            "Do not rely on over-the-counter blue-light glasses as a substitute for an eye exam",
            "Avoid further increasing screen time to push through symptoms",
        ),
        expected_timeline=(
            "Symptoms usually improve within days to two weeks of break discipline, ergonomic "
            "adjustment, and adequate hydration. Persistent visual symptoms warrant an eye exam."
        ),
        red_flags=(
            "Sudden vision loss",
            "Sudden onset of double vision that does not resolve",
            "Severe eye pain",
            "Halos around lights with eye redness",
        ),
        sources=(
            "American Optometric Association — Computer Vision Syndrome",
            "NIOSH — Computer Workstation Ergonomics",
        ),
        specialist_label="optometrist",
        specialist_osm_filters=(
            "healthcare=optometrist",
            "shop=optician",
        ),
    ),
    "tension_type_headache": Condition(
        id="tension_type_headache",
        name="Tension-type headache",
        defining_symptoms=(
            "Bilateral pressing or tightening pain, mild to moderate, like a band around the head",
            "No nausea, vomiting, or sensitivity to light or sound",
            "Often accompanied by neck and shoulder muscle tightness",
            "Onset late in the workday, with or after sustained desk posture",
        ),
        discriminators=(
            "Pain is bilateral and pressing rather than unilateral and pulsating (migraine)",
            "Routine activity does not worsen the headache",
            "No aura, no photophobia, no phonophobia",
        ),
        conservative_treatment=(
            "Take regular posture breaks; check monitor height, seat support, and keyboard position",
            "Apply gentle heat to the upper trapezius and posterior neck",
            "Practice slow breathing and relaxation during breaks; reduce sustained jaw clenching",
            "Maintain hydration and consistent sleep timing",
        ),
        contraindications=(
            "Do not stack over-the-counter pain medications across multiple days; rebound headache is a known risk",
            "Avoid prolonged static screen postures without movement breaks",
        ),
        expected_timeline=(
            "Episodes typically resolve within hours of removing the trigger. Frequent recurrences "
            "(more than a few days a week) over several weeks warrant a clinician visit."
        ),
        red_flags=(
            "Sudden severe headache, often described as the worst of the user's life",
            "Headache with fever and stiff neck",
            "New headache after head trauma",
            "Headache with new neurological symptoms — weakness, numbness, vision change, confusion",
        ),
        sources=(
            "International Classification of Headache Disorders (ICHD-3) — Tension-Type Headache",
            "AAFP — Diagnosis and Treatment of Tension-Type Headache",
        ),
        specialist_label="general practitioner",
        specialist_osm_filters=(
            "amenity=doctors",
            "healthcare=doctor",
            "healthcare=general_practitioner",
        ),
    ),
    "upper_trapezius_strain": Condition(
        id="upper_trapezius_strain",
        name="Upper trapezius / 'text neck' strain",
        defining_symptoms=(
            "Aching pain across the upper shoulders and base of the neck",
            "Stiffness reducing neck rotation, worse late in the workday",
            "Tender bands palpable in the upper trapezius",
            "Symptoms aggravated by forward-head posture and prolonged screen viewing",
        ),
        discriminators=(
            "Pain is muscular and posture-related rather than radicular",
            "No tingling, numbness, or weakness travelling down the arm",
            "Symptoms ease with movement and posture change rather than worsening",
        ),
        conservative_treatment=(
            "Raise the monitor so the top of the screen is at or just below eye level",
            "Take a brief posture and movement break every 30 to 45 minutes",
            "Perform gentle chin tucks and shoulder-blade retractions through the day",
            "Apply heat to the upper trapezius; consider self-massage of tender points",
        ),
        contraindications=(
            "Avoid aggressive neck cracking or end-range manipulation by an untrained party",
            "Do not push through sharp or radiating pain",
        ),
        expected_timeline=(
            "Posture-related strain commonly improves within two to four weeks of consistent "
            "ergonomic change and movement breaks. Persistence beyond four to six weeks warrants "
            "a clinician visit."
        ),
        red_flags=(
            "Numbness, tingling, or weakness travelling down an arm",
            "Sudden one-sided weakness or facial droop",
            "Severe neck pain after trauma",
            "Fever with neck stiffness",
        ),
        sources=(
            "AAOS OrthoInfo — Neck Pain",
            "American Physical Therapy Association — Posture and Neck Pain Guidance",
            "OSHA — Computer Workstation Ergonomics",
        ),
        specialist_label="physiotherapist",
        specialist_osm_filters=("healthcare=physiotherapist",),
    ),
    "lumbar_strain": Condition(
        id="lumbar_strain",
        name="Lumbar strain from prolonged sitting",
        defining_symptoms=(
            "Aching or stiff low-back pain that builds during the workday",
            "Worse with prolonged sitting; eased by standing or walking",
            "Localised to the lower back without radiation past the buttock",
            "No neurological symptoms in the legs",
        ),
        discriminators=(
            "Pain is mechanical and posture-related rather than radicular",
            "No leg numbness, tingling, or weakness",
            "Symptoms improve with movement, contrasting with inflammatory back pain that is worse with rest",
        ),
        conservative_treatment=(
            "Stand or walk for a few minutes at least every 30 minutes",
            "Adjust chair lumbar support; keep hips slightly above knees and feet flat",
            "Perform gentle hip-flexor stretches and core-engagement movements during breaks",
            "Apply heat in the early days; gradually return to normal activity",
            "Stay generally active rather than resting in bed",
        ),
        contraindications=(
            "Avoid prolonged bed rest beyond a day",
            "Avoid heavy lifting with a flexed and rotated spine while symptomatic",
        ),
        expected_timeline=(
            "Mechanical low-back pain commonly improves substantially within two to six weeks "
            "of postural change and graduated activity. Persistence beyond six weeks warrants "
            "a clinician visit."
        ),
        red_flags=(
            "Numbness or tingling in the saddle area between the legs",
            "New bowel or bladder dysfunction with back pain",
            "Progressive leg weakness",
            "Severe back pain after significant trauma",
            "Unexplained fever with back pain",
        ),
        sources=(
            "AAOS OrthoInfo — Low Back Pain",
            "American College of Physicians — Noninvasive Treatments for Acute, Subacute, and Chronic Low Back Pain",
            "OSHA — Ergonomics for Prolonged Sitting",
        ),
        specialist_label="physiotherapist",
        specialist_osm_filters=("healthcare=physiotherapist",),
    ),
}


_SECTION_TEMPLATE = """\
## {name} (id: {id})

Defining symptoms:
{defining_symptoms}

Discriminators:
{discriminators}

Conservative treatment:
{conservative_treatment}

Contraindications:
{contraindications}

Expected timeline:
{expected_timeline}

Condition-specific red flags:
{red_flags}

Sources:
{sources}\
"""


def _bullet_list(items: tuple[str, ...]) -> str:
    """Render a tuple of strings as a Markdown-style bulleted block."""
    return "\n".join(f"- {item}" for item in items)


def kb_for_prompt() -> str:
    """Render the condition catalogue as a stable, parseable prompt block.

    The returned string is embedded in the realtime model's system
    prompt at session start. Each condition contributes one ``## name``
    section so the model can reference records by name and id, and
    every field shows up in a fixed order so the prompt schema is
    stable across record additions.

    Pure function over :data:`CONDITIONS`; trivial to round-trip in
    tests.
    """
    sections: list[str] = []
    for condition in CONDITIONS.values():
        section = _SECTION_TEMPLATE.format(
            id=condition.id,
            name=condition.name,
            defining_symptoms=_bullet_list(condition.defining_symptoms),
            discriminators=_bullet_list(condition.discriminators),
            conservative_treatment=_bullet_list(condition.conservative_treatment),
            contraindications=_bullet_list(condition.contraindications),
            expected_timeline=condition.expected_timeline,
            red_flags=_bullet_list(condition.red_flags),
            sources=_bullet_list(condition.sources),
        )
        sections.append(section)
    return "\n\n".join(sections)


__all__ = ["CONDITIONS", "Condition", "kb_for_prompt"]
