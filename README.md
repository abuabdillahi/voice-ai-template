# Voice AI Assistant Template

A monorepo template for building voice AI assistant web applications. Real-time conversational voice via LiveKit Agents, defaulting to OpenAI Realtime as the speech-to-speech model. Backend in FastAPI, frontend in Vite + React.

The full specification lives at [`.scratch/voice-ai-template/PRD.md`](./.scratch/voice-ai-template/PRD.md). Implementation is broken down into independently-grabbable issues at [`.scratch/voice-ai-template/issues/`](./.scratch/voice-ai-template/issues/).

## Status

Foundation + auth tracer + voice loop tracer + tool-calling tracer + conversation persistence tracer + triage product layer. Workspace skeleton, tooling, Docker, the Supabase auth slice, the LiveKit + OpenAI Realtime voice loop, the tool-registration / dispatch layer, persisted conversation transcripts with the history pages, and the office-strain triage tools (`record_symptom`, `get_differential`, `recommend_treatment`, `escalate`, `find_clinician`) are in place.

## Conversation history

Every voice conversation is persisted as a `conversations` row plus one `messages` row per turn (user, assistant, tool). The agent worker writes the rows mid-session via `core.conversations`; on session end an LLM-generated one-line summary is attached when the conversation has at least three messages. The web app exposes the transcripts at:

- `/history` — list of past conversations with their summary and message count.
- `/history/:id` — full transcript for a single conversation, with role-styled bubbles and timestamps. Tool calls render as a third message type carrying the tool name, arguments, and result.

Audio recordings are explicitly **out of scope** per the PRD — only the text transcripts are persisted. RLS on both `conversations` and `messages` enforces user isolation at the database level.

## Getting started

### Prerequisites

- **[uv](https://docs.astral.sh/uv/)** ≥ 0.4 — Python package and workspace manager
- **[pnpm](https://pnpm.io/)** ≥ 9 — Node package manager (Corepack or Volta both work)
- **Node.js** ≥ 20

Recommended install via Volta (manages Node + pnpm) and Astral's installer (uv):

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
curl https://get.volta.sh | bash && volta install node pnpm
```

### Install

From the repo root:

```sh
pnpm install        # installs Node deps and links workspace packages
uv sync             # installs Python deps and links workspace packages
```

### One-time hook setup

After cloning, install the git hooks so commits and pushes are automatically
formatted, linted, type-checked, and rejected if the commit message is not in
[Conventional Commits](https://www.conventionalcommits.org) format:

```sh
uv run pre-commit install --install-hooks
uv run pre-commit install --hook-type pre-push
uv run pre-commit install --hook-type commit-msg
```

Run `uv run pre-commit run --all-files` once after install to confirm
everything is wired up.

### Common commands

All cross-cutting commands run through Turborepo from the repo root:

```sh
pnpm dev            # turbo run dev      (vite for web, uvicorn --reload for api, livekit-agents dev for agent)
pnpm build          # turbo run build
pnpm lint           # turbo run lint
pnpm test           # turbo run test
pnpm typecheck      # turbo run typecheck
```

## Running locally

The dev stack splits across two ecosystems:

- **`api` and `agent`** run in Docker via compose. Both services load environment variables from a top-level `.env` file (copy `.env.example` to `.env` first).
- **`web`** runs outside compose so Vite's HMR works directly against the host.

```sh
cp .env.example .env

# Bring up the Python services. api is exposed on http://localhost:8000;
# /health returns {"status": "ok"}.
docker compose up

# In a separate terminal:
pnpm --filter @voice-ai/web dev
```

For a production-shaped stack (api + agent + nginx-served web bundle):

```sh
docker compose -f docker-compose.prod.yml up --build
```

The production compose adds the nginx-served web bundle on top of the dev service graph. LiveKit itself is **not** in the compose stack — both dev and prod dial a hosted LiveKit Cloud project via `LIVEKIT_URL`. Use a separate Cloud project (or at minimum a separate API key/secret pair) for production traffic.

## Auth setup

The template uses Supabase for auth, Postgres, and (later) pgvector. Two flavours are supported:

### Option A — Supabase Cloud (zero-setup, free tier)

1. Create a project at <https://supabase.com>.
2. From **Project Settings → API** copy the **Project URL** and the **publishable key**. Paste them into `.env`:

   ```
   SUPABASE_URL=https://<ref>.supabase.co
   SUPABASE_PUBLISHABLE_KEY=<publishable-key>

   VITE_SUPABASE_URL=https://<ref>.supabase.co
   VITE_SUPABASE_PUBLISHABLE_KEY=<publishable-key>
   ```

   JWT verification uses the project's JWKS endpoint at `{SUPABASE_URL}/auth/v1/.well-known/jwks.json` — no `JWT_SECRET` required. (The legacy `SUPABASE_ANON_KEY` env var is still accepted as an alias for the publishable key, so `.env` files cloned before the 2026 rename keep working.)

3. (Optional) In **Authentication → Providers → Email** disable "Confirm email" if you want sign-ups to work without an SMTP server.

### Option B — Supabase local (self-hosted via the CLI)

1. Install the [Supabase CLI](https://supabase.com/docs/guides/cli).
2. From the repo root run `supabase start`. The CLI prints the local URL and publishable key — paste them into `.env` and the matching `VITE_SUPABASE_*` mirrors. Set `SUPABASE_JWKS_URL` to the local Supabase Auth JWKS URL the CLI prints if it differs from the standard `/auth/v1/.well-known/jwks.json` path.
3. Apply the bundled migrations: `supabase db reset`.

## Voice loop setup

The voice loop is real-time conversational audio over WebRTC, powered by LiveKit Agents in the backend and OpenAI Realtime as the speech-to-speech model. Two services need accounts.

### LiveKit

LiveKit owns the media plane (signalling + RTP). Both dev and prod use a hosted LiveKit Cloud project — there is no self-hosted media server in this template.

1. Create a project at <https://cloud.livekit.io>. The free tier is sufficient for development; provision a separate project (or at minimum a separate API key/secret pair) for production traffic.
2. From **Project Settings → Keys** copy the **API Key**, **API Secret**, and the **WebSocket URL** (`wss://<project>.livekit.cloud`). Paste them into `.env`:

   ```
   LIVEKIT_URL=wss://<project>.livekit.cloud
   LIVEKIT_API_KEY=<api-key>
   LIVEKIT_API_SECRET=<api-secret>
   ```

3. The agent worker dispatches into rooms automatically; no further LiveKit dashboard configuration is needed for the demo.

LiveKit lives behind `LIVEKIT_URL` — nothing in `apps/api`, `apps/agent`, or `apps/web` cares whether the URL points at LiveKit Cloud or a self-hosted server. A fork that needs to self-host can swap the URL and add a `livekit-server` service to the compose stack without touching application code.

### OpenAI

The default realtime model is OpenAI's `gpt-realtime`.

1. Create an account at <https://platform.openai.com> and provision an API key under **API keys**. The key needs access to the realtime model family.
2. Paste it into `.env`:

   ```
   OPENAI_API_KEY=sk-<your-key>
   ```

Subsequent slices may swap providers; the swap point is a single function in `core.realtime`. See `core/realtime.py` for the seam.

### Per-user database writes from the agent

The agent worker writes to RLS-protected tables (`conversations`, `messages`, `safety_events`) on behalf of the signed-in user. To honour those policies, it needs the user's Supabase JWT — Supabase RLS keys off `auth.uid()`, which is derived from the bearer token, not from a service role.

The token reaches the agent via the **LiveKit participant metadata**:

1. Frontend POSTs `/livekit/token` with its Supabase access token in the `Authorization: Bearer …` header.
2. The API route mints a LiveKit access token whose `metadata` claim holds `{"supabase_access_token": "<jwt>"}`.
3. Frontend uses that token to join the room.
4. Agent worker calls `_resolve_supabase_token(ctx)` at session start, parses the metadata, and forwards the JWT to every `core.conversations` / `core.safety_events` call it makes on the user's behalf.

**Security note.** LiveKit metadata is decodable by anyone holding the LiveKit access token. In this template that is acceptable — the same client (the signed-in user's browser) already holds the Supabase JWT in its session storage, so embedding it in the LiveKit token does not widen its exposure. **Downstream apps with stricter requirements** (shared rooms, spectator participants, third-party agents) should pass the token through a server-side relay instead — e.g. a separate `POST /agent/dispatch` call that issues the LiveKit token without metadata and forwards the Supabase JWT directly to the agent worker through a private channel.

### Observability

The agent worker emits one structured `turn_metrics` JSON log line per LiveKit metric event (LLM TTFT, TTS TTFB, end-of-utterance delay, etc.) on stdout. The line carries the bound `session_id` and `user_id` contextvars, so a single conversation is grep-able from the worker's log stream:

```sh
docker logs voice-ai-agent | grep turn_metrics
```

A sample line:

```json
{
  "event": "turn_metrics",
  "metric_type": "llm_metrics",
  "label": "openai-llm",
  "request_id": "req-1",
  "ttft": 0.18,
  "duration": 0.42,
  "completion_tokens": 42,
  "prompt_tokens": 7,
  "total_tokens": 49,
  "session_id": "room-abc",
  "user_id": "user-7",
  "log_level": "info",
  "timestamp": "2026-05-04T00:00:00Z"
}
```

This is the minimum-viable monitoring agreed in the PRD. A richer observability stack — Langfuse for LLM traces, dashboards for aggregated latency, and client-side TTFA capture — is deferred to a future iteration.

## Adding tools

Tools are the assistant's capabilities — anything beyond pure conversation. The template ships two example tools (`get_current_time`, `get_weather`) that demonstrate the canonical pattern. They live in [`packages/core/core/tools/examples.py`](./packages/core/core/tools/examples.py).

To add a new tool:

1. Write an async function in a module under `core.tools` (or a downstream package). Decorate it with `@tool` from `core.tools`. The decorator captures the function name, the first paragraph of the docstring, and the JSON schema derived from the type-hinted parameters.

   ```python
   from core.tools import tool

   @tool
   async def lookup_user_orders(user_email: str) -> str:
       """Look up the most recent orders placed by a customer."""
       ...
   ```

2. Import the module once at process start so the decorator runs. `core.tools.__init__` imports `core.tools.examples` for the bundled tools; mirror that pattern for your own module.

3. **Use `httpx.AsyncClient` with an explicit timeout** for any outbound HTTP, and return a graceful natural-language string when the upstream fails. Errors raised inside a tool handler are caught by `core.tools.dispatch` and returned to the model as `{"error": ...}` so the agent verbalises the failure rather than crashing the session.

4. **Announce the tool in the system prompt** so the realtime model knows it can call it. The prompt lives at the top of `apps/agent/agent/session.py` (`SYSTEM_PROMPT`). Tools that aren't mentioned in the prompt rarely get called, even when registered.

The tool's first parameter may optionally be typed as `ToolContext` to receive the authenticated `User` plus a structlog logger pre-bound with `tool_name`. The dispatcher injects it automatically and hides it from the model's schema.

The `core.tools` registry is the only seam adapters use to enumerate or invoke tools. The agent worker calls `all_tools()` at session start to register them with LiveKit; future API endpoints can reuse the same registry without LiveKit being involved.

### Generating the typed API client

The frontend's `src/api/types.gen.ts` is generated from the FastAPI OpenAPI schema. Regenerate it whenever a route's request or response shape changes:

```sh
# In one terminal, with .env populated:
pnpm --filter @voice-ai/api dev

# In another:
pnpm --filter @voice-ai/web gen:api
```

The script reads `apps/api/openapi.json` (committed for offline builds) and writes `apps/web/src/api/types.gen.ts`.

## Layout

```
voice-ai/
├── apps/
│   ├── web/              # Vite + React SPA (frontend)
│   ├── api/              # FastAPI HTTP backend
│   └── agent/            # LiveKit Agents worker (voice loop)
├── packages/
│   └── core/             # Shared Python: domain logic, triage, safety, conversations
├── docs/agents/          # Configuration for agent skills
├── .scratch/             # PRDs and implementation issues (local issue tracker)
├── pyproject.toml        # uv workspace root
├── pnpm-workspace.yaml   # pnpm workspace
├── turbo.json            # task pipeline
└── package.json          # pnpm + turbo entry points
```

`apps/api` and `apps/agent` consume `packages/core` via uv workspace dependencies. `apps/web` is the only TypeScript consumer; types for the API are generated into the web app rather than into a shared package.
