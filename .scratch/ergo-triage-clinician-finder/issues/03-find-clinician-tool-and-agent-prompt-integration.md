# Issue 03: `find_clinician` tool, system prompt updates, agent registration, privacy-doc update

Status: ready-for-agent

## Parent

`.scratch/ergo-triage-clinician-finder/PRD.md`

## What to build

Wire the `core.clinician` module from slice 02 into the realtime triage agent as a model-callable tool, and update the system prompt with the offer flow, the verbal read-back, the filler line, the post-result spoken summary, and the new hard rule against speaking unsourced clinician names. After this slice lands, a developer running `pnpm dev` can have a voice conversation, complete an OPQRST interview that lands on a known condition, accept the clinician offer, give a city verbally, and watch the agent return a tool-call payload with real OSM data — without yet having a polished UI for rendering it (slice 04 handles the UI).

The tool wrapper is thin. It validates inputs, calls `core.clinician.find_clinics`, and returns the JSON string verbatim. All of the business logic — geocoding, the Overpass query, the radius fallback ladder, the failure handling, the structured logging — already lives in `core.clinician` and is tested in isolation by slice 02. The wrapper's tests cover only the tool-dispatch contract.

The system prompt grows by one new section, two new module-level constants, and one extension to `TRIAGE_TOOL_NAMES`. The new prompt language is verbatim per the design grilling. The existing `_wire_safety_screen` is unchanged — emergent and urgent escalations still close the session structurally, blocking the model from pivoting to clinician finding on those paths regardless of the prompt.

The privacy paragraph in `.scratch/ergo-triage/PRD.md` is updated in the same diff so the existing PRD's "no PHI by design" claim stays accurate when this feature ships. The update is honest accounting: the user's spoken locality already lands in `messages.content` via the existing persistence hook regardless of this feature; what this feature adds is the same data in machine-readable form on the tool-args / tool-result rows.

When `OSM_CONTACT_EMAIL` is unset, the tool is not registered for the session and the system prompt branches to omit the offer language entirely. Misconfiguration produces a silently-disabled feature, not a runtime "maps service unavailable" surface that would surprise a user mid-conversation.

## Acceptance criteria

- [ ] New tool in `packages/core/core/tools/triage.py`:
  ```python
  @tool(
      name="find_clinician",
      description=(
          "Find healthcare providers near the user, scoped to the specialist "
          "appropriate for the given condition. Call this only after a successful "
          "`recommend_treatment` or a `clinician_soon` escalation, and only after "
          "the user has verbally consented AND confirmed their location with a "
          "read-back. The condition_id must match one of the ids in the embedded "
          "knowledge base. The location is a short free-form locality string (city, "
          "town, or postcode) — the tool geocodes it via OpenStreetMap. Returns a "
          "JSON object with the resolved locality, the radius searched, and a list "
          "of up to 5 nearby clinics (name, address, phone, OSM URL, distance_km). "
          "On failure, returns a JSON object with an `error` field; paraphrase that "
          "error to the user — do not invent results."
      ),
  )
  async def find_clinician(ctx: ToolContext, condition_id: str, location: str) -> str
  ```
  Validates `condition_id` against `core.conditions.CONDITIONS` and `location` non-empty before delegating to `core.clinician.find_clinics`. Returns whatever `find_clinics` returns.

- [ ] Module-level constant `FIND_CLINICIAN_RESULT_LIMIT = 5` exported from `core.tools.triage` for symmetry with the existing `RECOMMEND_TREATMENT_CONFIDENCE_THRESHOLD`. Referenced from the prompt language so the limit and the prompt stay in lockstep.

- [ ] `TRIAGE_TOOL_NAMES` in `apps/agent/agent/session.py` is extended:
  ```python
  TRIAGE_TOOL_NAMES: tuple[str, ...] = (
      "record_symptom",
      "get_differential",
      "recommend_treatment",
      "escalate",
      "find_clinician",
  )
  ```

- [ ] New module-level constant `_TRIAGE_CLINICIAN_NAMES_RULE` in `apps/agent/agent/session.py` alongside the existing `_TRIAGE_OPENER_RULE` and `_TRIAGE_NUMBERS_RULE`:
  ```python
  _TRIAGE_CLINICIAN_NAMES_RULE = (
      "Never speak a clinic name, address, or phone number that did not come "
      "from a `find_clinician` tool result on this turn. The model's own "
      "knowledge is not a source for clinician names."
  )
  ```

- [ ] `_build_static_triage_prompt()` gains a new section, inserted between the existing `recommend_treatment` paragraph and the cross-session recall rules. The section's wording matches the verbatim draft from the design grilling — six numbered steps covering offer-as-question, verbal location capture, read-back, filler line, tool invocation, and post-result spoken summary; followed by the hard rule on clinician names; followed by the bypass-blocking rule (no offer on emergent/urgent paths, no tool call without a known condition_id). The `_TRIAGE_CLINICIAN_NAMES_RULE` constant is referenced from the rendered prompt rather than inlined a second time.

- [ ] When `settings.osm_contact_email` is unset (`None` / empty string), `find_clinician` is unregistered for the session. `apps/agent/agent/session.py::build_agent` filters it out of the `TRIAGE_TOOL_NAMES` list before constructing the LiveKit tool wrappers. The system prompt branch in `_build_static_triage_prompt()` omits the offer language entirely so the model is not instructed to call a tool that does not exist. Startup-time warning log: `agent.find_clinician.disabled_no_contact_email`.

- [ ] When `settings.osm_contact_email` is set, the existing prompt rendering and tool registration path includes the new section and the new tool. The empty-input invariance rule from the recall feature still holds: with no prior sessions and `find_clinician` enabled, the rendered prompt is the new static prompt with the find-clinician section present.

- [ ] The existing `_wire_safety_screen` is unchanged. Tier-1 (`emergent`) and tier-2 (`urgent`) red flags continue to close the session immediately via `session.aclose()` after the scripted message plays. The model has no further turn on which to pivot to clinician finding on those paths. The prompt-side bypass rule is belt-and-braces; the structural floor is the safety-screen close.

- [ ] Unit tests for `find_clinician` in `core.tools.triage`:
  - Happy path: structured payload returned, tool dispatch returns a string the realtime model can verbalise.
  - Unknown `condition_id`: returns the failure-taxonomy row #1 string.
  - Empty `location`: returns the failure-taxonomy row #2 string.
  - Other failure rows are covered in slice 02 and not duplicated here — the wrapper's contract is only "delegate to `core.clinician.find_clinics`."

- [ ] Unit tests for `build_agent` and `_build_static_triage_prompt`:
  - With `osm_contact_email` set, `find_clinician` appears in the agent's registered tools list and the rendered prompt contains the new section verbatim.
  - With `osm_contact_email` unset, `find_clinician` is absent from the agent's registered tools list and the rendered prompt omits the offer language.
  - The `_TRIAGE_CLINICIAN_NAMES_RULE` constant string appears verbatim in the rendered prompt when the feature is enabled.
  - The empty-input invariance from the recall feature still holds: `build_triage_system_prompt([])` with the feature enabled produces a prompt byte-for-byte equal to the new static prompt baseline.

- [ ] Agent-session integration test (`apps/agent/tests/integration/`):
  - Mocked realtime model fires `find_clinician(condition_id="carpal_tunnel", location="Brooklyn")`.
  - Mocked Nominatim and Overpass HTTP responses return canned data.
  - Asserts the tool-call event is forwarded on `lk.tool-calls` with `name == "find_clinician"`.
  - Asserts the `messages.tool_result` row contains the expected payload (specialist_label, location_resolved, results array).
  - Asserts the `agent.tool_call` log line is emitted with the right tool name and no error.

- [ ] Privacy paragraph update in `.scratch/ergo-triage/PRD.md`:
  - The "Out of Scope" → "HIPAA compliance" paragraph and any related "no PHI by design" claim is amended to acknowledge that voluntary locality disclosure during clinician-finding lands in the transcript with the same RLS protection as the rest of the messages. Wording: "The MVP collects no clinical identifiers by design — the persisted `messages` and `safety_events` rows contain symptom descriptions and, when the user voluntarily discloses a locality during clinician-finding, that locality. No name, date of birth, address-line, or other PII is collected. RLS continues to enforce per-user isolation; the same data set is what a returning user sees in their own `/history/:id` view."

- [ ] No frontend changes in this slice. Tool-call results are forwarded on `lk.tool-calls` (the existing topic) and the existing transcript-view will render them as a generic tool-call row until slice 04 adds the dedicated `<ClinicianSuggestions>` component.

- [ ] No safety-eval changes in this slice; slice 05 covers the bypass-blocking scripts.

## Blocked by

`.scratch/ergo-triage-clinician-finder/issues/01-add-specialist-mapping-fields-to-condition.md`,
`.scratch/ergo-triage-clinician-finder/issues/02-core-clinician-nominatim-overpass-plumbing.md`

## Comments

> *This was generated by AI during triage.*

### Agent Brief

**Category:** enhancement

**Summary:** Wire the slice-02 `core.clinician` module into the realtime triage agent as a `find_clinician` tool, extend the system prompt with the offer flow and the new hard rule against speaking unsourced clinician names, and update the existing PRD's privacy paragraph to acknowledge voluntary locality disclosure. After this slice lands, a developer running `pnpm dev` can complete an OPQRST interview, accept the clinician offer, give a city verbally, and watch the agent return a real OSM-sourced result payload.

The "What to build" narrative and "Acceptance criteria" sections above already cover the verbatim system-prompt language (six numbered steps: offer-as-question, location capture, read-back, filler line, tool invocation, post-result spoken summary; followed by the hard rule on clinician names and the bypass-blocking rule), the `@tool` decorator description string, the `_TRIAGE_CLINICIAN_NAMES_RULE` module-level constant alongside the existing `_TRIAGE_OPENER_RULE` and `_TRIAGE_NUMBERS_RULE`, the `TRIAGE_TOOL_NAMES` extension, the `osm_contact_email`-unset feature-flag branch (tool unregistered, prompt branches to omit offer language), the integration-test shape with mocked Nominatim and Overpass HTTP, and the privacy-paragraph wording update for `.scratch/ergo-triage/PRD.md`. Treat those as the contract.

**Out of scope** (see PRD `.scratch/ergo-triage-clinician-finder/PRD.md` for the full list): no frontend rendering changes (slice 04); no safety-eval scripts (slice 05); no schema migration (the existing `messages` table covers persistence via the existing `_persist_tool_message` and `_wire_conversation_persistence` hooks); no new ADR for the OSM-vendor choice (deferred per the PRD until pilot coverage data is available); no changes to `_wire_safety_screen` (the existing tier-1 / tier-2 session-close path is the structural floor for bypass blocking on emergent and urgent escalation paths); no condition_id parameter added to the existing `escalate` tool (the model fills `condition_id` for `find_clinician` from the slot history on the `clinician_soon` path).
