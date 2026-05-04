# Agents Guide

This file orients agentic tools (Claude Code, Cursor, etc.) working in this repository. Human contributors should also read it.

## Project

A monorepo template for voice AI assistant web applications. The runtime stack is real-time conversational voice via LiveKit Agents, defaulting to OpenAI Realtime as the speech-to-speech model. The full PRD lives at `.scratch/voice-ai-template/PRD.md`.

## Cold-start reading order

A new agent landing on this repo should read, in order:

1. **This file** — locate scaffold + reading order.
2. **`docs/adr/`** — five accepted ADRs covering the load-bearing decisions (LiveKit Agents, Pattern C shared `core` package, Supabase + RLS, hybrid memory, JWKS verification). Each one is ~80 lines and answers "why is it like this?" before the agent goes spelunking through the code.
3. **`.scratch/voice-ai-template/PRD.md`** — full architecture in one read. ~290 lines.
4. **`docs/GOTCHAS.md`** — verbatim error → cause → fix. Grep here first when debugging anything that resembles a known failure mode (auth, mem0, voice loop, env config).
5. **`README.md`** — how to actually run it (prerequisites, env vars, demo flow).
6. **`git log --oneline`** — conventional commits, scannable. Recent fixes are the freshest signal.

Issue files under `.scratch/voice-ai-template/issues/` are historical — read them only when extending or replicating a specific slice.

## Repo layout

```
apps/                          # thin transport adapters
  web/                         # Vite + React + TanStack Router + shadcn
  api/                         # FastAPI HTTP backend
  agent/                       # LiveKit Agents worker
packages/
  core/                        # shared Python: domain logic, schema, memory layer
docs/
  adr/                         # accepted architectural decisions
  agents/                      # agent-skill scaffold (issue tracker, triage labels, domain layout)
  GOTCHAS.md                   # symptom → fix index
supabase/
  migrations/                  # SQL migrations applied via supabase db push
.scratch/voice-ai-template/    # PRD + per-slice issue files (local issue tracker)
```

The deep-vs-shallow split is non-negotiable: anything substantial belongs in `packages/core`; the `apps/*` layers translate transport events into core calls. See ADR 0002.

## Agent skills

### Issue tracker

Issues and PRDs live as markdown files under `.scratch/<feature-slug>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default canonical role strings (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout — one `CONTEXT.md` and one `docs/adr/` at the repo root, shared by all apps and packages. See `docs/agents/domain.md`.
