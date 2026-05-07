# Issue 02: `core.clinician` module — Nominatim + Overpass plumbing

Status: ready-for-agent

## Parent

`.scratch/ergo-triage-clinician-finder/PRD.md`

## What to build

A new pure-function deep module `core.clinician` that owns every interaction with OpenStreetMap. The module's single public entrypoint takes a `condition_id` and a free-form locality string and returns up to five nearby healthcare providers, scoped to the specialist appropriate for the condition. The module wraps two upstream HTTP services — Nominatim (geocoding) and Overpass (POI search) — and is the only place in the codebase where their wire shapes are referenced.

Every failure path returns a verbalisable result that the realtime model can paraphrase to the user; nothing in this module raises through to the agent worker. The radius fallback ladder (10 km → 25 km → 50 km → empty) treats sparse OSM coverage as a first-class case rather than an exception. The deterministic LRU cache for Nominatim and the async semaphore enforcing 1 req/sec are how the OSMF usage policy is honoured at MVP scale.

The module is testable in isolation. Tests mock `httpx.AsyncClient` at the boundary, the same way `tests/unit/test_safety.py` mocks the OpenAI client for the safety classifier. No agent worker, no LiveKit harness, no live network call. The agent integration in slice 03 picks this module up via the tool wrapper.

`OSM_CONTACT_EMAIL` is a required environment variable threaded through the typed `Settings` module. When unset, the module's behaviour is defined: the public entrypoint returns the network-unavailable failure string and a warning is logged. Slice 03 reads the same setting at agent worker startup to decide whether to register the `find_clinician` tool at all; this slice ensures the module degrades cleanly when the setting is missing.

## Acceptance criteria

- [ ] New module `packages/core/core/clinician.py` with one public async function:
  ```python
  async def find_clinics(
      condition_id: str,
      location: str,
      *,
      settings: Settings,
  ) -> str
  ```
  Returns a JSON-encoded string — either the success payload or one of the failure payloads from the failure taxonomy below. Never raises.

- [ ] Success payload shape (JSON-encoded):
  ```json
  {
    "specialist_label": "physiotherapist",
    "location_resolved": "Brooklyn, Kings County, New York, United States",
    "radius_km": 10,
    "results": [
      { "name": "...", "address": "...", "phone": "...",
        "url": "https://www.openstreetmap.org/node/<id>", "distance_km": 1.2 },
      ...
    ],
    "count": 5
  }
  ```

- [ ] Geocoding step calls Nominatim at `settings.nominatim_base_url` (defaults to `https://nominatim.openstreetmap.org`, overridable via `NOMINATIM_BASE_URL`). Top hit selected; `display_name` becomes `location_resolved`; `lat` / `lon` parsed as floats.
- [ ] POI query step builds an Overpass QL `union` query from the condition's `specialist_osm_filters`, queries `settings.overpass_base_url` (defaults to `https://overpass-api.de/api/interpreter`, overridable via `OVERPASS_BASE_URL`), parses the response, deduplicates by OSM node id.
- [ ] Radius fallback ladder: try 10 km. If 0 results after dedup, retry at 25 km. If still 0, retry at 50 km. If still 0, return the failure-taxonomy row #6 (zero-results-after-ladder) graceful string.
- [ ] Top 5 results returned, sorted ascending by haversine distance from the geocoded point. Each result has: `name` (from `name` tag), `address` (assembled from `addr:*` tags or the place's `display_name` fallback), `phone` (from `phone` or `contact:phone`, may be empty string when missing), `url` (`https://www.openstreetmap.org/node/<id>` or way/relation equivalent), `distance_km` (rounded to one decimal).
- [ ] In-process LRU cache for Nominatim, 256 entries, 24-hour TTL, keyed on the lower-cased trimmed locality string. Cache hits skip the Nominatim HTTP call entirely. Overpass results are NOT cached.
- [ ] Process-local async semaphore enforcing Nominatim's 1 req/sec policy. Implemented via `asyncio.Semaphore` plus a per-acquire delay so the public Nominatim instance is not pounded.
- [ ] `User-Agent` header on every Nominatim and Overpass request: `voice-ai-ergo-triage/<version> (<contact-email>)`. Version comes from the package metadata; contact email comes from `settings.osm_contact_email`.
- [ ] Per-call HTTP timeouts: 5 seconds for Nominatim, 8 seconds for Overpass. Total tool budget 12 seconds enforced via `asyncio.wait_for` around the whole entrypoint. No retries.
- [ ] `Settings` (in `packages/core/core/config.py`) gains three new fields: `osm_contact_email: str | None`, `nominatim_base_url: str`, `overpass_base_url: str`. The first is optional at the typed-Settings level; absence is handled by `find_clinics` returning the network-unavailable string.
- [ ] Failure taxonomy — every row returns the listed JSON-encoded `{"error": "..."}` string and emits a structured log line:
  - `condition_id` not in `CONDITIONS` → `"I don't have a referral path for that condition. Let me know what you've been experiencing and we can take it from the top."`
  - `location` is empty / whitespace → `"I didn't catch a location — could you tell me what city or area you're in?"`
  - `osm_contact_email` is `None` → network-unavailable string (below). Startup-time warning log emitted by `core.config` validation.
  - Nominatim returns 0 results → `"I couldn't find a place called <user_string> on the map — could you give me a town name or postcode?"`
  - Overpass returns 0 results after the radius ladder → `"I couldn't find any <specialist_label> tagged in OpenStreetMap within 50 km of <resolved_locality>. Your best bet is to search Google Maps for '<specialist_label> near <resolved_locality>' directly."`
  - Network error (timeout, DNS, 5xx, 429), malformed response, or 12s total budget exceeded → `"I couldn't reach the maps service just now. Try Google Maps for '<specialist_label> near <user_string>' instead."`
- [ ] Every failure path emits a structured log line via `structlog`. Log fields include `condition_id`, `location`, `resolved_locality` (when reached), `radius_km` (when reached), `source` (`nominatim` or `overpass`), and the HTTP status / exception class. Event names: `clinician.upstream_failed`, `clinician.zero_results`, `clinician.budget_exceeded`, `clinician.misconfigured`.
- [ ] Unit tests at the `httpx.AsyncClient` boundary, mocked. Coverage:
  - Happy path: known condition_id, known location → 5 results, `location_resolved` populated, `radius_km == 10`.
  - Nominatim response parsing: top hit selected, `display_name` mapped, lat/lon parsed.
  - Overpass query construction: per condition, the OR-joined filter list produces one Overpass QL query with a `union` block; the `around:RADIUS,LAT,LON` is correct for each rung of the ladder.
  - Result dedup: a node tagged with multiple matching filters appears once.
  - Distance calculation: haversine output matches a manual fixture to within rounding tolerance.
  - Radius fallback ladder: 10 km returns 0 → 25 km returns 0 → 50 km returns 5 → result has `radius_km == 50`.
  - Empty after full ladder: returns the failure-taxonomy row #6 string.
  - LRU cache hit: same locality within TTL skips Nominatim call.
  - Each failure-taxonomy row returns the listed string.
  - `osm_contact_email` is `None`: returns the network-unavailable string; warning log emitted.
- [ ] No changes to `apps/agent`, `apps/web`, or any tool-registry surface in this slice. The module is the deep seam; the tool wrapper that registers it is slice 03.

## Blocked by

`.scratch/ergo-triage-clinician-finder/issues/01-add-specialist-mapping-fields-to-condition.md`

## Comments

> *This was generated by AI during triage.*

### Agent Brief

**Category:** enhancement

**Summary:** New `core.clinician` deep module wrapping Nominatim (geocoding) and Overpass (POI search) behind a single `find_clinics(condition_id, location)` async entrypoint, with a deterministic radius-fallback ladder, an LRU cache, an async semaphore enforcing the OSMF 1 req/sec policy, and a fully-enumerated failure taxonomy.

The "What to build" narrative and "Acceptance criteria" sections above already cover the public function shape, the success and error JSON payloads, the radius ladder (10 → 25 → 50 km → graceful fallback), the OSMF usage-policy obligations (User-Agent with contact email, 1 req/sec for Nominatim, 256-entry / 24-hour LRU cache), the per-call HTTP timeouts (5s Nominatim / 8s Overpass) and total tool budget (12s), the Settings extension for `osm_contact_email` / `nominatim_base_url` / `overpass_base_url`, and the structured-logging shape per failure path. Treat those as the contract.

**Out of scope** (see PRD `.scratch/ergo-triage-clinician-finder/PRD.md` for the full list): no agent-worker integration or LiveKit-side wiring (slice 03); no tool registration in the `core.tools` registry (slice 03); no UI rendering (slice 04); no safety-eval scripts (slice 05); no Overpass result caching (results are per-(condition, location) and stale data is worse than re-querying); no retries on transient failures (failing fast preserves the 12s budget); no fuzzy "did you mean" spelling-suggestion layer for Nominatim mishears (the verbal read-back in the agent slice is the disambiguation mechanism); no localisation of OSM tag synonyms beyond the five English-speaking-world filter sets the conditions ship with.
