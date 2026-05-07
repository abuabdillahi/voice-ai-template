# ADR 0002: Pattern C — shared `packages/core` Python library

Status: Accepted (2026-05-04)
Supersedes: —

## Context

The runtime has two Python services that both perform business logic: the FastAPI HTTP backend (`apps/api`) and the LiveKit Agents worker (`apps/agent`). Both need to read/write user preferences, conversation rows, mem0 memories. Without a sharing strategy, logic gets duplicated and drifts.

Three ways to share:

- **Pattern A — Agent owns logic.** Tools in the agent worker write to the DB directly. FastAPI is auth + token issuance only.
- **Pattern B — Agent calls FastAPI.** Tools are HTTP clients of FastAPI endpoints. One source of truth, network hop per call.
- **Pattern C — Shared package.** Both services import from `packages/core`. In-process calls.

## Decision

Use **Pattern C — shared `packages/core`**. Domain logic, schema, memory layer, observability live in `packages/core`. Both `apps/api` and `apps/agent` `pip install -e packages/core` via uv workspaces and import freely.

Each app is a **shallow adapter**: routes / event handlers translate transport-specific events into `core` calls and contain no business logic. Adding a new entrypoint (CLI, telephony bridge) means a new adapter, never a new core module.

## Consequences

**Positive**

- One place to change a rule. Schema, validation, RLS-token plumbing all live in `core`.
- No internal HTTP hops. Tool dispatch, persistence, memory writes are in-process function calls.
- Integration tests can drive `core` directly without spinning up an HTTP server.
- The deep-vs-shallow split makes review easy — anything substantial belongs in `core`; adapters should be thin.
- Realises the actual reason this is a monorepo. Without Pattern C, the monorepo is cosmetic.

**Negative**

- Three Python packages (`core`, `api`, `agent`) instead of two. uv workspaces handles this transparently.
- A "what goes in core?" judgment call on every change. The rule of thumb: if a future entrypoint would need it, it goes in core.
- Pattern C couples deploy boundaries — bumping a shared `core` interface requires both apps to redeploy. Pattern B's HTTP boundary lets one side change ahead. Acceptable for a template; revisit if downstream apps split into separate repos.

## Alternatives considered

- **Pattern A.** Rejected. Logic duplication the moment the web UI and the agent both need to write a preference. Two services owning the schema is a recipe for drift.
- **Pattern B.** Rejected. Network hop on every tool call (20–80ms), more auth complexity (api needs to authenticate the agent), and we lose the single-process-test advantage. Sensible if the agent ever has to scale on a different topology than the api, but premature for a template.

## Pointers

- `packages/core/core/` — the shared package's modules.
- `apps/api/api/routes.py` — adapter shape (HTTP → core call).
- `apps/agent/agent/session.py::_make_livekit_tool` — adapter shape (LiveKit tool → core dispatch).
- `.scratch/sarjy/PRD.md` "Monorepo shape and shared logic" section.
