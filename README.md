# Sarjy

Voice-first triage assistant for office-strain symptoms — wrist tingling, eye strain, tension headaches, neck strain, lumbar pain. The user clicks Connect, talks, and Sarjy walks them through an OPQRST-style symptom interview. The session ends in one of three ways: a self-care routine, a clinician referral surfaced via OpenStreetMap, or — rarely — an emergent/urgent routing message.

Sarjy is **explicitly not a doctor**. The product layer enforces a deliberately narrow scope (five conditions, defined in [`packages/core/core/conditions.py`](./packages/core/core/conditions.py)) and routes anything outside that scope away.

The runtime stack is real-time conversational voice via LiveKit Agents on top of OpenAI's `gpt-realtime` speech-to-speech model. The backend is FastAPI + Supabase; the frontend is Vite + React + TanStack Router with shadcn/ui.

## What's in the box

- **Voice loop** — LiveKit + OpenAI Realtime, with a separate `gpt-4o-mini-tts` attached for the safety-script playback (see [ADR 0007](./docs/adr/0007-tts-attached-safety-escalation.md)).
- **OPQRST triage** — `record_symptom`, `get_differential`, `recommend_treatment` tools backed by the static condition catalogue.
- **Safety floor** — a server-side regex + classifier screen runs in parallel with the model on every committed user utterance. Either tier-1/tier-2 hit triggers a deterministic teardown coordinated by `core.escalation.EscalationCoordinator`: scripted message verbatim, audit row, session-end signal, room delete.
- **Clinician finder** — `find_clinician` tool that geocodes via Nominatim and queries Overpass for nearby healthcare amenities (radius ladder 10 → 25 → 50 km).
- **Conversation history** — every session is persisted as a `conversations` row plus per-turn `messages` rows, with a one-line LLM-generated summary on close. Surfaces at `/history` and `/history/:id`.
- **Cross-session recall** — the most recent prior `identified_condition_id` + free-text recall context is injected into the system prompt at session start so a returning user gets a short refresher instead of the full disclaimer.

For the runtime architecture in one read, see [`docs/architecture.md`](./docs/architecture.md). For the design decisions behind the choices below, see [`docs/adr/`](./docs/adr/).

## Prerequisites

- **[uv](https://docs.astral.sh/uv/)** ≥ 0.4 — Python package and workspace manager
- **[pnpm](https://pnpm.io/)** ≥ 9 — Node package manager (Corepack or Volta both work)
- **Node.js** ≥ 20

Recommended install via Volta (manages Node + pnpm) and Astral's installer (uv):

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
curl https://get.volta.sh | bash && volta install node pnpm
```

## Install

From the repo root:

```sh
pnpm install        # installs Node deps and links workspace packages
uv sync             # installs Python deps and links workspace packages
```

### One-time hook setup

After cloning, install the git hooks so commits and pushes are automatically formatted, linted, type-checked, and rejected if the commit message is not in [Conventional Commits](https://www.conventionalcommits.org) format:

```sh
uv run pre-commit install --install-hooks
uv run pre-commit install --hook-type pre-push
uv run pre-commit install --hook-type commit-msg
```

Run `uv run pre-commit run --all-files` once after install to confirm everything is wired up.

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
pnpm --filter @sarjy/web dev
```

For a production-shaped stack (api + agent + nginx-served web bundle):

```sh
docker compose -f docker-compose.prod.yml up --build
```

LiveKit itself is **not** in the compose stack — both dev and prod dial a hosted LiveKit Cloud project via `LIVEKIT_URL`. Self-hosting is supported (a fork only needs to flip the URL and add `livekit/livekit-server` as a service) but is not the default posture.

## Environment setup

### Supabase (auth + Postgres)

Sarjy uses Supabase for auth, Postgres, and Row-Level Security. Two flavours are supported:

#### Option A — Supabase Cloud (zero-setup, free tier)

1. Create a project at <https://supabase.com>.
2. From **Project Settings → API** copy the **Project URL** and the **publishable key**. Paste them into `.env`:

   ```
   SUPABASE_URL=https://<ref>.supabase.co
   SUPABASE_PUBLISHABLE_KEY=<publishable-key>

   VITE_SUPABASE_URL=https://<ref>.supabase.co
   VITE_SUPABASE_PUBLISHABLE_KEY=<publishable-key>
   ```

   JWT verification uses the project's JWKS endpoint at `{SUPABASE_URL}/auth/v1/.well-known/jwks.json` — no `JWT_SECRET` required. (The legacy `SUPABASE_ANON_KEY` env var is still accepted as an alias for the publishable key.)

3. (Optional) In **Authentication → Providers → Email** disable "Confirm email" if you want sign-ups to work without an SMTP server.

#### Option B — Supabase local (self-hosted via the CLI)

1. Install the [Supabase CLI](https://supabase.com/docs/guides/cli).
2. From the repo root run `supabase start`. The CLI prints the local URL and publishable key — paste them into `.env` and the matching `VITE_SUPABASE_*` mirrors. Set `SUPABASE_JWKS_URL` to the local Supabase Auth JWKS URL the CLI prints if it differs from the standard `/auth/v1/.well-known/jwks.json` path.
3. Apply the bundled migrations: `supabase db reset`.

### LiveKit (media plane)

LiveKit owns signalling + RTP. Both dev and prod dial a hosted LiveKit Cloud project.

1. Create a project at <https://cloud.livekit.io>. The free tier is sufficient for development; provision a separate project (or at minimum a separate API key/secret pair) for production traffic.
2. From **Project Settings → Keys** copy the **API Key**, **API Secret**, and the **WebSocket URL** (`wss://<project>.livekit.cloud`). Paste them into `.env`:

   ```
   LIVEKIT_URL=wss://<project>.livekit.cloud
   LIVEKIT_API_KEY=<api-key>
   LIVEKIT_API_SECRET=<api-secret>
   ```

3. The agent worker dispatches into rooms automatically; no further LiveKit dashboard configuration is needed.

### OpenAI (realtime model + safety TTS + classifier)

Sarjy uses three OpenAI surfaces: `gpt-realtime` for the conversation, `gpt-4o-mini-tts` for the safety-script playback, and `gpt-4o-mini` for the classifier half of the red-flag screen.

1. Create an account at <https://platform.openai.com> and provision an API key with access to the realtime model family.
2. Paste it into `.env`:

   ```
   OPENAI_API_KEY=sk-<your-key>
   ```

The realtime model lives behind a single seam — `core.realtime.create_realtime_model(settings)` — so swapping providers (Gemini Live, an Anthropic real-time offering, a self-hosted pipeline) is a config change, not a refactor.

### OpenStreetMap (clinician finder)

The `find_clinician` tool calls Nominatim for geocoding and Overpass for healthcare-amenity queries. Both are free and require no API key, but Nominatim's [usage policy](https://operations.osmfoundation.org/policies/nominatim/) requires a contact email in the User-Agent header. Set:

```
OSM_CONTACT_EMAIL=ops@yourdomain.example
```

If `OSM_CONTACT_EMAIL` is unset the agent worker drops `find_clinician` from the registered tool set and gates the clinician-finding section out of the system prompt — the model is never told to call a tool that isn't there.

## Per-user database writes from the agent

The agent worker writes to RLS-protected tables (`conversations`, `messages`, `safety_events`) on behalf of the signed-in user. To honour those policies, it needs the user's Supabase JWT — RLS keys off `auth.uid()`, which is derived from the bearer token, not from a service role.

The token reaches the agent through two channels:

1. **LiveKit token metadata.** The frontend POSTs `/livekit/token` with its Supabase access token. The API route mints a LiveKit access token whose `metadata` claim holds `{"supabase_access_token": "<jwt>"}`. The agent reads this at session start.
2. **Participant attribute, live.** The frontend pushes the same token as a participant attribute and refreshes it on every Supabase `TOKEN_REFRESHED` event. The agent listens for attribute changes so long sessions stay authenticated past the 1h JWT TTL.

The agent prefers the live attribute when present and falls back to the metadata claim.

**Security note.** LiveKit metadata is decodable by anyone holding the LiveKit access token. For Sarjy this is acceptable — the same client (the signed-in user's browser) already holds the Supabase JWT in `localStorage`, so embedding it in the LiveKit token does not widen its exposure. Deployments with shared rooms or third-party agent participants should route the JWT through a server-side relay instead.

## Observability

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

This is the minimum-viable monitoring path. A richer stack — Langfuse for LLM traces, dashboards for aggregated latency, client-side TTFA capture — is deferred.

## Generating the typed API client

The frontend's `src/api/types.gen.ts` is generated from the FastAPI OpenAPI schema. Regenerate it whenever a route's request or response shape changes:

```sh
# In one terminal, with .env populated:
pnpm --filter @sarjy/api dev

# In another:
pnpm --filter @sarjy/web gen:api
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
│   └── core/             # Shared Python: triage, safety, escalation, conversations, clinician
├── docs/
│   ├── architecture.md   # Runtime architecture in one read
│   ├── adr/              # Accepted architectural decisions
│   └── GOTCHAS.md        # Symptom → fix index for known failure modes
├── supabase/migrations/  # SQL migrations applied via supabase db push
├── pyproject.toml        # uv workspace root
├── pnpm-workspace.yaml   # pnpm workspace
├── turbo.json            # task pipeline
└── package.json          # pnpm + turbo entry points
```

`apps/api` and `apps/agent` consume `packages/core` via uv workspace dependencies. `apps/web` is the only TypeScript consumer; types for the API are generated into the web app rather than into a shared package.
