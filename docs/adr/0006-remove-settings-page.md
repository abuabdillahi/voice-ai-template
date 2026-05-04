# ADR 0006: Remove the `/settings` page

Status: Accepted (2026-05-04)
Supersedes: —

## Context

Issue 10 shipped a `/settings` route as a tracer-bullet for "thin CRUD against the existing preferences API." The page let the user edit two preference keys (`preferred_name`, `voice`) via an RHF + zod form and exposed sign-out. It pulled in a TypeScript mirror of `core.preferences.OPENAI_REALTIME_VOICES` (`apps/web/src/lib/voice-options.ts`) so the voice select could render synchronously.

The intent was to model the pattern downstream forks would copy when building their own preference-editing UIs. In practice the page added surface area without earning its keep:

- **Two preference keys is not a compelling demo.** A fork building a real settings UI will diverge from this scaffold immediately — different keys, different validation, different layout — so the copy-target value is thin.
- **The agent already exercises the read path.** `MemorySidebar` consumes `GET /preferences` and the agent worker reads `preferred_name` + `voice` at session start. The "preferences exist and are user-scoped" story is told without the form.
- **Sign-out belongs in the persistent nav, not on a destination page.** Hiding it behind a route the user has to navigate to was friction.
- **Template clarity beats demo breadth.** Every concept in the template is a concept a reader has to load before they can change anything. Removing one is a real win.

## Decision

Delete the `/settings` route, the `SettingsForm` component, its test, and the `voice-options.ts` TS mirror. Move sign-out into the home route's nav.

**Backend kept.** `PUT /preferences/{key}` and `core.preferences.validate_preference` stay live. They have no in-template caller now, but they are a stable public API surface — a downstream fork's settings UI, a CLI, or an admin tool can all call them. The recognised-key catalogue still gates the validated write path; only the framing in the comments changes (no longer "the UI is the only caller").

The agent's unvalidated free-form path through `core.tools.preferences.set_preference` is unaffected.

## Consequences

**Positive**

- One fewer route, one fewer form, one fewer TS↔Python list to keep in sync.
- Sign-out is one click from the home page instead of two.
- `core.preferences` reads as "a validator for the write API" rather than "a list shaped by what the settings UI happens to surface."

**Negative**

- Forks that wanted a working settings form to copy now start from `MemorySidebar` (read path) plus the API spec for `PUT /preferences/{key}`. Slightly less hand-holding; not a big jump.
- `PUT /preferences/{key}` is currently caller-less in this template. The endpoint and its tests still pay rent as a documented API surface, but a future cleanup might decide the cost of carrying an uncalled endpoint exceeds its illustrative value.

## Alternatives considered

- **Keep the page as illustrative.** Rejected — see Context. The illustrative payoff is small relative to the cognitive load.
- **Delete the backend write path too.** Rejected for now. The validator is small, well-tested, and the most likely first thing a fork wires a UI against. Removing it now would just force the fork to rewrite `validate_preference` against the same key catalogue.

## Pointers

- `apps/web/src/routes/index.tsx` — sign-out lives here in the nav.
- `apps/web/src/components/memory-sidebar.tsx` — read path for `GET /preferences`, the surviving demo of the preferences API on the frontend.
- `packages/core/core/preferences.py` — `OPENAI_REALTIME_VOICES`, `validate_preference`. Catalogue is still the contract for `PUT /preferences/{key}`.
- `apps/api/api/routes.py` — `PUT /preferences/{key}` endpoint kept; no in-template caller.
