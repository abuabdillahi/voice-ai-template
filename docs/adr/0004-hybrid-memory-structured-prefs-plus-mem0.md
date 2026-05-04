# ADR 0004: Hybrid memory — structured preferences + mem0 episodic

Status: Accepted (2026-05-04)
Supersedes: —

## Context

A voice assistant template that claims cross-session memory needs a working memory layer. The user-stated test case ("what's my favorite color?") is small but the design must scale to richer state ("I'm learning Spanish," "my daughter is named Maya"). Three OSS memory libraries dominated in 2026:

- **mem0** — most popular, opinionated extract-and-dedupe pipeline, pgvector backend, ~30k stars.
- **Letta** (formerly MemGPT) — sophisticated tiered memory model, runs as a separate server.
- **Zep / Graphiti** — temporal knowledge graph, separate server.

A fourth path exists: **roll-your-own on pgvector** (~150 lines, full control).

There's also a structural question: is memory one thing, or two? "Favorite color" is a named preference (deterministic key-value). "User is learning Spanish" is a fuzzy fact better stored as embeddings. Forcing both through the same machinery is suboptimal.

## Decision

**Hybrid: structured preferences table + mem0 for episodic memory.**

- **Structured preferences.** A `user_preferences (user_id, key, value)` table. Agent has `set_preference(key, value)` / `get_preference(key)` tools. Used for any single-valued named fact — favorite color, preferred name, language, dietary needs. Deterministic, debuggable, fast.
- **Episodic memory.** Mem0 with pgvector backend (against the same Supabase Postgres). Agent has `remember(content)` / `recall(query)` tools. Used for fuzzy facts that don't fit a named key — interests, relationships, things the user is learning.
- **Preferences are inlined into the agent's system prompt at session start.** A "Known facts about the user" block lets the model verbalise stored preferences without a tool call. The system prompt explicitly forbids `recall` for facts that have a structured key.

Mem0's LLM is pinned to `gpt-4o-mini` (see `GOTCHAS.md` for why the default fails on newer OpenAI accounts).

## Consequences

**Positive**

- Two tools, two purposes. Forcing "favorite color" through similarity search is silly; forcing "user is learning Spanish" into a key-value table is silly. The split matches how memory actually behaves.
- Same Postgres instance handles both — one database, one backup, one set of RLS policies.
- mem0 handles dedup, conflict-on-update ("I have a daughter Maya" → "I have two daughters, Maya and Ana"), and similarity search out of the box.
- Inlining preferences in the prompt makes cross-session recall reliable — the model doesn't have to choose the right tool, the answer is already in context.
- Roll-your-own avoided. Reimplementing dedup + fact-update logic in 150 lines would feel worse than mem0 in production.

**Negative**

- Two memory abstractions to teach contributors. The boundary ("name it as a preference, or store it as a memory?") is judgment.
- mem0 evolves quickly — kwarg shape has already shifted twice in this template's lifetime (see `GOTCHAS.md`).
- mem0's fact-extraction calls OpenAI on every `add` — first-write latency ~3–5s, costs tokens.
- pgvector under Supabase's transaction pooler doesn't support prepared statements; we've documented session pooler as the requirement.

## Alternatives considered

- **mem0 alone.** Rejected. "Favorite color" via similarity search is unreliable and slow. The deterministic path is missing.
- **Structured preferences alone.** Rejected. Falls over the moment the user mentions something not anticipated as a column.
- **Letta or Zep.** Rejected. Separate server with its own conceptual model; over-scoped for a template that downstream apps will heavily customize.
- **Roll-your-own.** Rejected. Skips the hard parts (dedup, conflict resolution) and produces a memory layer that feels worse than a real product's.

## Pointers

- `packages/core/core/preferences.py` — structured side.
- `packages/core/core/memory.py` — mem0 wrapper (with the `gpt-4o-mini` pin).
- `supabase/migrations/0001_user_preferences.sql`, `0003_mem0_memories.sql`.
- `apps/agent/agent/session.py::build_system_prompt` — Known-facts inlining.
- `.scratch/voice-ai-template/PRD.md` "Memory" section.
- `docs/GOTCHAS.md` "Memory" section.
