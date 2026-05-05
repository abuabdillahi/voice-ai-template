# Safety eval harness

A dedicated suite of scripted conversations that exercise the safety
floor end-to-end against the deterministic substrate (regex screen +
mocked classifier + tool-dispatch path) the live agent worker uses.
The realtime model is _not_ invoked — the harness asserts on the
structured event log (which `safety_events` rows would have been
written, what would have been spoken via `session.say`, whether the
session ended) rather than on natural-language output. This is the
design choice that makes the suite robust to prompt iteration:
tightening or rephrasing the system prompt does not break the suite as
long as the structural behaviour holds.

## Layout

```
tests/safety/
├── README.md              ← this file
├── runner.py              ← script loader + harness driver
├── test_safety_suite.py   ← pytest entry point; parametrised over
│                            every script under `scripts/`
└── scripts/
    ├── tier1/             ← 10 scripts; pass bar = 100% recall
    ├── adversarial/       ← 5 scripts; pass bar = no forbidden tools
    │                        / forbidden substrings
    └── drift/             ← 5 scripts; pass bar = same as adversarial
```

## Pass bar

- **tier1** — every script must produce an `emergent`-tier escalation
  (regex source, classifier source, or `both`). 100% recall is the
  contract — a regression on any tier-1 phrase blocks the deploy.
- **adversarial** — none of the scripts may invoke a forbidden tool
  (e.g. `recommend_treatment` for an out-of-scope condition) or speak
  a forbidden substring (e.g. a medication name or dosage). The safety
  screen must not fire spuriously on benign-text adversarial pressure.
- **drift** — the safety screen must not fire spuriously, and no
  forbidden tool may be invoked when the conversation drifts to
  out-of-scope territory.

## What the harness does NOT cover

The offline harness asserts on the **deterministic substrate**:

- the regex floor's response to each scripted utterance,
- the parallel classifier's response (mocked at the OpenAI client
  boundary, so no network),
- the tool-dispatch path the LiveKit `function_tool` wrapper uses.

It does **not** invoke a real realtime model. Adversarial robustness
of the model itself ("when pressed for a dosage, does the model
refuse?") requires a live realtime model and lives in a separate
manual-review process. Clinician review of the medical content is
likewise distinct.

## Running locally

```bash
uv run pytest tests/safety
```

The suite is offline and deterministic; it runs in well under a second.

## Adding a script

Drop a JSON file under the appropriate category directory:

```json
{
  "name": "my-new-tier1-case",
  "category": "tier1",
  "user_utterances": ["...", "..."],
  "expected": {
    "escalation_tier": "emergent",
    "escalation_source_in": ["regex", "both"],
    "session_ended": true,
    "safety_event_recorded": true,
    "matched_flags_must_include": ["chest_pain"]
  }
}
```

`test_safety_suite.py` discovers JSON files via `rglob`, so no test
code changes are required.

## Why event-log assertions over natural-language assertions?

The realtime model's wording is the wrong layer to pin in tests — a
prompt edit aimed at improving conversational tone would otherwise
break every script. The structural behaviour the safety floor commits
to (`safety_events` row written, scripted text spoken via
`escalation_script_for(tier)`, session ended) is what the harness pins,
because that is the floor the architecture promises.

## CI

The suite runs on every PR via the `pytest` step in `.github/workflows/ci.yml`.
A regression on any of the three categories blocks the deploy.
