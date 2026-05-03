# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Layout: single-context

This is a polyglot monorepo (TypeScript frontend, Python API and agent worker, shared Python core), but the **domain is shared** across all services — they are different layers expressing the same voice-AI-assistant domain rather than separate bounded contexts. Single-context is the right shape; if the domain ever splits (e.g. a billing context appears alongside the assistant), promote to multi-context with a `CONTEXT-MAP.md`.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root, when it exists
- **`docs/adr/`** — read ADRs that touch the area you're about to work in, when they exist

If any of these files don't exist yet, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The producer skill (`/grill-with-docs`) creates them lazily when terms or decisions actually get resolved.

## File structure

```
/
├── CONTEXT.md            ← domain glossary (lazy: created when terms are resolved)
├── docs/adr/             ← architectural decisions (lazy: created when decisions land)
│   └── …
├── apps/
│   ├── web/              ← Vite + React SPA
│   ├── api/              ← FastAPI
│   └── agent/            ← LiveKit Agents worker
└── packages/
    └── core/             ← shared Python domain logic
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal — either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/grill-with-docs`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0007 (memory layer storage) — but worth reopening because…_
