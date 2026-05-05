# Issue 01: Triage pivot tracer

Status: needs-triage

## Parent

`.scratch/ergo-triage/PRD.md`

## What to build

The first vertical slice that converts the generic voice assistant template into the office-strain triage product. After this slice, a user signing in and clicking the talk button hears an educational triage agent — disclaimer up front, scope statement, OPQRST-style opening question — even though the agent cannot yet structure the interview, recommend a treatment, or escalate on red flags. This is the tracer bullet that proves the medical-domain pivot lands cleanly through the prompt, the agent worker, and the frontend together.

The slice introduces the static condition knowledge base as a deep, pure-data module: five condition records (carpal tunnel syndrome, computer vision syndrome, tension-type headache, upper trapezius / "text neck" strain, lumbar strain) typed as a `Condition` dataclass and rendered into the system prompt via a `kb_for_prompt()` helper. Each record carries defining symptoms, discriminators, conservative treatment, contraindications, expected timeline, condition-specific red flags, and source citations from public clinical guidance.

The agent worker drops the preferences and memory tools from its tool registration and bypasses the preference-aware system-prompt personalisation, using the new medical-domain `SYSTEM_PROMPT` instead. The structured-preferences and episodic-memory modules remain in source as kept public API per the precedent set by ADR 0006. The frontend's homepage copy is replaced with the disclaimer banner, the scope statement, and the prominent talk button; the memory sidebar is removed from the layout.

## Acceptance criteria

- [ ] `core.conditions` module exposes `Condition` dataclass, `CONDITIONS: dict[str, Condition]`, and `kb_for_prompt() -> str`. Five condition records are populated with content sourced from NIOSH, OSHA, AAOS, or physiotherapy association guidance. Source citations are present in every record.
- [ ] Unit tests cover the `Condition` dataclass shape and the `kb_for_prompt` round-trip — every record contributes a stable, parseable block that includes name, defining symptoms, conservative treatment, condition-specific red flags, and at least one source citation.
- [ ] `apps/agent/agent/session.py` `SYSTEM_PROMPT` is the medical-domain prompt. It embeds `kb_for_prompt()`, includes the educational-tool disclaimer, names the five in-scope conditions, names the out-of-scope categories (medications, mental health, pregnancy, paediatric, post-surgical, anything outside the five), instructs the model to interview using OPQRST slots, and instructs the model never to invent dosages, durations, or numerical specifics.
- [ ] The agent's tool registration no longer includes `set_preference`, `get_preference`, `remember`, `recall`, `get_current_time`, or `get_weather`. The corresponding modules remain in source unchanged.
- [ ] The agent worker no longer calls `_load_user_preferences` or the preference-aware `build_system_prompt` — the medical-domain prompt is used unconditionally. Conversation persistence, metrics logging, and the supabase-token refresh hook are unchanged.
- [ ] `apps/web/src/routes/index.tsx` (or its equivalent root) shows the educational-tool disclaimer, names the five in-scope conditions, and presents a talk button. The memory sidebar is removed from the layout.
- [ ] A frontend component test asserts the disclaimer text and talk button render.
- [ ] Running the dev stack and connecting from a browser produces a voice loop in which the agent greets the user with the disclaimer and asks an opening symptom question.
- [ ] No regression in existing agent integration tests beyond those whose subject (preferences, memory tools) is being unregistered. Any such tests are either marked skipped or moved to assert the post-pivot behaviour.

## Blocked by

None — can start immediately.
