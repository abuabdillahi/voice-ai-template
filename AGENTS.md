# Agents Guide

This file orients agentic tools (Claude Code, Cursor, etc.) working in this repository. Human contributors should also read it.

## Project

limber is a voice-first triage product for office-strain symptoms (carpal tunnel, computer vision syndrome, tension-type headache, upper trapezius strain, lumbar strain). The voice agent's persona is **Brook**. The runtime stack is real-time conversational voice via LiveKit Agents on top of OpenAI's `gpt-realtime` speech-to-speech model. The original product spec — written when the project was a slice of a larger voice-AI template, under the working name "Sarjy" — lives at `.scratch/sarjy/PRD.md` and remains the source of truth for product decisions.

## Cold-start reading order

A new agent landing on this repo should read, in order:

1. **This file** — orientation + reading order.
2. **`docs/architecture.md`** — runtime architecture in one read (~540 lines): topology, voice loop, data-channel topics, triage product layer, persistence + RLS, auth, escalation, tool registry, deployment, code map.
3. **`docs/adr/`** — seven accepted ADRs covering the load-bearing decisions (LiveKit Agents, shared `core` package, Supabase + RLS, hybrid memory, JWKS verification, settings page removal, TTS-attached safety escalation). Each is ~80 lines and answers "why is it like this?" before spelunking through the code. ADR 0004 (hybrid memory) describes a feature that has since been removed; the decision is preserved as historical context.
4. **`docs/GOTCHAS.md`** — verbatim error → cause → fix. Grep here first when debugging anything that resembles a known failure mode (auth, voice loop, env config).
5. **`README.md`** — how to actually run it (prerequisites, env vars, dev flow).
6. **`git log --oneline`** — conventional commits, scannable. Recent fixes are the freshest signal.

Issue files under `.scratch/sarjy/issues/` are historical — read them only when extending or replicating a specific slice.

## Repo layout

```
apps/                          # thin transport adapters
  web/                         # Vite + React + TanStack Router + shadcn
  api/                         # FastAPI HTTP backend
  agent/                       # LiveKit Agents worker
packages/
  core/                        # shared Python: triage, safety, escalation, conversations, clinician
docs/
  architecture.md              # runtime architecture in one read
  adr/                         # accepted architectural decisions
  agents/                      # agent-skill scaffold (issue tracker, triage labels, domain layout)
  GOTCHAS.md                   # symptom → fix index
supabase/
  migrations/                  # SQL migrations applied via supabase db push
.scratch/sarjy/    # PRD + per-slice issue files (local issue tracker)
```

The deep-vs-shallow split is non-negotiable: anything substantial belongs in `packages/core`; the `apps/*` layers translate transport events into core calls. See ADR 0002.

## Agent skills

### Issue tracker

Issues and PRDs live as markdown files under `.scratch/<feature-slug>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default canonical role strings (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout — one `docs/architecture.md` and one `docs/adr/` at the repo root, shared by all apps and packages. See `docs/agents/domain.md`.
