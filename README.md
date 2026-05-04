# Voice AI Assistant Template

A monorepo template for building voice AI assistant web applications. Real-time conversational voice via LiveKit Agents, defaulting to OpenAI Realtime as the speech-to-speech model. Backend in FastAPI, frontend in Vite + React.

The full specification lives at [`.scratch/voice-ai-template/PRD.md`](./.scratch/voice-ai-template/PRD.md). Implementation is broken down into independently-grabbable issues at [`.scratch/voice-ai-template/issues/`](./.scratch/voice-ai-template/issues/).

## Status

Foundation only. The runtime applications have not been built yet — current state is the workspace skeleton, with apps and packages as empty stubs. Subsequent issues add tooling, Docker, auth, the voice loop, tools, memory, and persistence in that order.

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

For a production-shaped stack (api + agent + nginx-served web bundle):

```sh
docker compose -f docker-compose.prod.yml up --build
```

The `livekit-server` slot in `docker-compose.prod.yml` is commented out and is wired in issue 05.

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
