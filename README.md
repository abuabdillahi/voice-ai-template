# Voice AI Assistant Template

A monorepo template for building voice AI assistant web applications. Real-time conversational voice via LiveKit Agents, defaulting to OpenAI Realtime as the speech-to-speech model. Backend in FastAPI, frontend in Vite + React.

The full specification lives at [`.scratch/voice-ai-template/PRD.md`](./.scratch/voice-ai-template/PRD.md). Implementation is broken down into independently-grabbable issues at [`.scratch/voice-ai-template/issues/`](./.scratch/voice-ai-template/issues/).

## Status

Foundation + auth tracer + voice loop tracer + tool-calling tracer. Workspace skeleton, tooling, Docker, the Supabase auth slice, the LiveKit + OpenAI Realtime voice loop, and the tool-registration / dispatch layer with two example tools are in place. Subsequent issues add memory and persistence.

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
pnpm dev            # turbo run dev      (no-ops at this stage)
pnpm build          # turbo run build
pnpm lint           # turbo run lint
pnpm test           # turbo run test
pnpm typecheck      # turbo run typecheck
```

Real implementations of these scripts arrive in subsequent issues.

## Running locally

The dev stack splits across two ecosystems:

- **`api` and `agent`** run in Docker via compose. Both services load environment variables from a top-level `.env` file (copy `.env.example` to `.env` first).
- **`web`** runs outside compose so Vite's HMR works directly against the host. It will be wired up in issue 04; until then `pnpm dev` is a no-op.

```sh
cp .env.example .env

# Bring up the Python services. api is exposed on http://localhost:8000;
# /health returns {"status": "ok"}.
docker compose up

# In a separate terminal (once issue 04 lands):
pnpm --filter @voice-ai/web dev
```

For a production-shaped stack (api + agent + nginx-served web bundle + self-hosted LiveKit):

```sh
docker compose -f docker-compose.prod.yml up --build
```

The production compose runs `livekit/livekit-server` alongside the application services. Defaults live in `livekit.yaml`; production deployers must replace the placeholder API key/secret pair (matching `.env`) and tune the UDP RTP port range to their network plan.

## Auth setup

The template uses Supabase for auth, Postgres, and (later) pgvector. Two flavours are supported:

### Option A — Supabase Cloud (zero-setup, free tier)

1. Create a project at <https://supabase.com>.
2. From **Project Settings → API** copy the **Project URL**, **anon public key**, and **JWT Secret** (under "JWT Settings"). Paste them into `.env`:

   ```
   SUPABASE_URL=https://<ref>.supabase.co
   SUPABASE_ANON_KEY=<anon-public-key>
   SUPABASE_JWT_SECRET=<jwt-secret>

   VITE_SUPABASE_URL=https://<ref>.supabase.co
   VITE_SUPABASE_ANON_KEY=<anon-public-key>
   ```

3. (Optional) In **Authentication → Providers → Email** disable "Confirm email" if you want sign-ups to work without an SMTP server.

### Option B — Supabase local (self-hosted via the CLI)

1. Install the [Supabase CLI](https://supabase.com/docs/guides/cli).
2. From the repo root run `supabase start`. The CLI prints the local URL, anon key, and JWT secret — paste them into `.env` and the matching `VITE_SUPABASE_*` keys.
3. Apply the bundled migrations: `supabase db reset`.

## Voice loop setup

The voice loop is real-time conversational audio over WebRTC, powered by LiveKit Agents in the backend and OpenAI Realtime as the speech-to-speech model. Two services need accounts.

### LiveKit

LiveKit owns the media plane (signalling + RTP). The dev posture is hosted; the production posture is self-hosted in compose.

#### Development — LiveKit Cloud (recommended)

1. Create a free project at <https://cloud.livekit.io>.
2. From **Project Settings → Keys** copy the **API Key**, **API Secret**, and the **WebSocket URL** (`wss://<project>.livekit.cloud`). Paste them into `.env`:

   ```
   LIVEKIT_URL=wss://<project>.livekit.cloud
   LIVEKIT_API_KEY=<api-key>
   LIVEKIT_API_SECRET=<api-secret>
   ```

3. The agent worker dispatches into rooms automatically; no further LiveKit dashboard configuration is needed for the demo.

#### Production — self-hosted (`docker-compose.prod.yml`)

The production compose file boots `livekit/livekit-server` alongside the application services. Configure it via the committed `livekit.yaml`:

1. Replace the placeholder line under `keys:` with the same `LIVEKIT_API_KEY: LIVEKIT_API_SECRET` pair you set in `.env`.
2. Adjust the UDP RTP port range (`50000-50100` by default) and TURN block to match your network. Tight NATs typically need a real TURN-over-TCP shared secret.
3. Update `LIVEKIT_URL` in `.env` to point at the in-cluster service (`ws://livekit-server:7880`) or the public hostname behind your TLS-terminating proxy.

Switching between cloud and self-hosted is a single environment-variable change from the application's perspective; nothing in `apps/api`, `apps/agent`, or `apps/web` is aware of where LiveKit lives.

### OpenAI

The default realtime model is OpenAI's `gpt-realtime`.

1. Create an account at <https://platform.openai.com> and provision an API key under **API keys**. The key needs access to the realtime model family.
2. Paste it into `.env`:

   ```
   OPENAI_API_KEY=sk-<your-key>
   ```

Subsequent slices may swap providers; the swap point is a single function in `core.realtime`. See `core/realtime.py` for the seam.

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
│   └── core/             # Shared Python: domain logic, schema, memory layer
├── docs/agents/          # Configuration for agent skills
├── .scratch/             # PRDs and implementation issues (local issue tracker)
├── pyproject.toml        # uv workspace root
├── pnpm-workspace.yaml   # pnpm workspace
├── turbo.json            # task pipeline
└── package.json          # pnpm + turbo entry points
```

`apps/api` and `apps/agent` consume `packages/core` via uv workspace dependencies. `apps/web` is the only TypeScript consumer; types for the API are generated into the web app rather than into a shared package.
