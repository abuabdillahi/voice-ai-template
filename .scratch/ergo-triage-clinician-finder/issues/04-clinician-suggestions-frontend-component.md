# Issue 04: `<ClinicianSuggestions>` frontend component + history-page support

Status: ready-for-agent

## Parent

`.scratch/ergo-triage-clinician-finder/PRD.md`

## What to build

A dedicated React component renders `find_clinician` tool-call results as a card list in the live conversation view and in the `/history/:id` past-conversation view. The component branches off the existing `lk.tool-calls` topic subscriber on `name === 'find_clinician'`; no new data-channel topic is added.

Five clinics with names, addresses, and phone numbers is too much to TTS aloud — the model only speaks a one-line summary naming the closest clinic and pointing at the on-screen list. The full structured payload renders here. Each card has a clickable `tel:` phone link so the user can call without retyping a number, an OSM-record link so the data source is verifiable, and a distance for ranking. The component footer carries the OSM ODbL attribution required by the upstream license.

The component has four distinct visual states. **In-flight** (the tool-call event has been forwarded with `result === null`) shows a spinner and the verbal-filler echo ("Searching around your area…") so the user gets visual feedback during the upstream HTTP latency. **Success** renders the card list. **Zero-results** renders the graceful "search Google Maps directly" message returned by the tool's failure-taxonomy row #6. **Error** renders the network-error message from row #7. The state machine is keyed off the tool-call payload's `result` field and the parsed JSON inside it; no separate progress channel is needed.

The same component renders in `/history/:id` so a returning user can dig out a phone number from a past suggestion that they did not call at the time. Tool-call rows in `messages` already persist with the full `tool_args` and `tool_result` JSON via the existing `_persist_tool_message` hook, so the history page has everything it needs — no new query, no new endpoint.

## Acceptance criteria

- [ ] New component `apps/web/src/components/clinician-suggestions.tsx` (or wherever the existing tool-rendering / transcript components live; match the local convention).
- [ ] The component accepts a tool-call payload prop with the JSON shape from slice 02:
  ```ts
  type FindClinicianResult =
    | { specialist_label: string; location_resolved: string; radius_km: number;
        results: Array<{ name: string; address: string; phone: string;
                         url: string; distance_km: number }>;
        count: number }
    | { error: string };
  ```
- [ ] The transcript subscriber for `lk.tool-calls` is extended (in whatever existing module owns it) to branch on `name === 'find_clinician'` and render `<ClinicianSuggestions>` instead of the generic tool-call row. All other tool names continue to render via the generic path.
- [ ] **In-flight state.** When the tool-call event has `result === null` (tool dispatched, not yet returned), the component renders a spinner with the text "Searching around your area…" so the user has visual feedback during the upstream HTTP latency.
- [ ] **Success state.** Renders a card list. Header: `"<specialist_label> near <location_resolved> — within <radius_km> km"`. One card per result, ordered by `distance_km` ascending. Each card shows: `name` (heading), `address` (single line, may wrap), `phone` rendered as `<a href="tel:...">` when non-empty (omitted when empty), `distance_km` formatted to one decimal with km suffix, and a "view on OpenStreetMap" link to `url` opening in a new tab.
- [ ] **Zero-results state.** When the tool's parsed result has shape `{ error: <row-6-string> }`, render the error string verbatim with no card list.
- [ ] **Error state.** When the tool's parsed result has shape `{ error: <other-string> }` (network error, unknown condition, empty location, etc.), render the error string verbatim with no card list.
- [ ] **Footer.** The component footer carries the OSM ODbL attribution: `"Sourced from © OpenStreetMap contributors"` with a link to `https://www.openstreetmap.org/copyright`. Required by ODbL.
- [ ] **History-page support.** `/history/:id` renders the same `<ClinicianSuggestions>` component for any past `messages` row where `tool_name === 'find_clinician'`. The existing `messages.tool_args` and `messages.tool_result` JSON columns supply the props. No new API endpoint.
- [ ] No changes to `lk.tool-calls` topic subscription or `_wire_tool_call_forwarding`. The agent worker is unchanged in this slice.
- [ ] No new data-channel topic. The component reads from the existing `lk.tool-calls` event stream that the transcript view already subscribes to.
- [ ] Vitest + Testing Library tests:
  - Happy-path payload (5 results) renders 5 cards with the expected name, address, phone link, distance, and OSM link.
  - Empty `phone` field omits the `tel:` link rather than rendering an empty link.
  - Header reflects the `specialist_label`, `location_resolved`, and `radius_km` from the payload.
  - In-flight state (`result === null`) shows the spinner and the "Searching around your area…" text.
  - Zero-results error string renders verbatim with no card list.
  - Network-error string renders verbatim with no card list.
  - Footer attribution is present in every state.
- [ ] No changes to the agent worker, the system prompt, the `core.clinician` module, or the safety eval in this slice.

## Blocked by

`.scratch/ergo-triage-clinician-finder/issues/03-find-clinician-tool-and-agent-prompt-integration.md`

## Comments

> *This was generated by AI during triage.*

### Agent Brief

**Category:** enhancement

**Summary:** A `<ClinicianSuggestions>` React component renders `find_clinician` tool-call results as a card list in the live conversation view and in the `/history/:id` past-conversation view, with four states (in-flight, success, zero-results, error) keyed off the parsed tool-call payload's `result` field. Branched off the existing `lk.tool-calls` topic subscriber on `name === 'find_clinician'`; no new data-channel topic.

The "What to build" narrative and "Acceptance criteria" sections above already cover the four-state state machine, the per-card layout (name, address, clickable `tel:` phone link, distance to one decimal, "view on OpenStreetMap" link), the OSM ODbL attribution footer required by the upstream license, the existing `lk.tool-calls` subscriber branch on tool name, and the history-page reuse path that reads from the persisted `messages.tool_args` and `messages.tool_result` JSON columns without any new API endpoint. Treat those as the contract.

**Out of scope** (see PRD `.scratch/ergo-triage-clinician-finder/PRD.md` for the full list): no agent-worker changes (the tool-call event stream is already wired by slice 03); no new data-channel topic (reuse `lk.tool-calls`); no new API endpoint for the history page (the existing `messages` rows already carry the structured payload via `_persist_tool_message`); no live-update animation when a card is added; no embedded map-rendering UI (the user follows the OSM link or `tel:` link to act on a result); no user-facing "save / favourite this clinic" feature; no in-component retry-on-failure button (a retry is a fresh agent turn, not a UI button).
