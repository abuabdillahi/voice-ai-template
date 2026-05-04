# ADR 0001: LiveKit Agents as the realtime voice framework

Status: Accepted (2026-05-04)
Supersedes: —

## Context

The template needs to support real-time conversational voice (full-duplex WebRTC, sub-second TTFA). Three reasonable shapes existed in 2026:

1. **OpenAI Realtime direct** — simplest: one vendor, one SDK, lowest raw latency for speech-to-speech.
2. **LiveKit Agents** — a Python framework around a media server; provider-agnostic; can wrap OpenAI Realtime as one model option, or run a classic STT→LLM→TTS pipeline.
3. **Roll-your-own** WebRTC + STT/LLM/TTS pipeline.

Each shape has a different blast radius for vendor lock-in, observability, telephony reach, and latency.

## Decision

Use **LiveKit Agents** as the realtime framework, defaulting to OpenAI Realtime as the swappable model.

The realtime model lives behind a single seam — `core.realtime.create_realtime_model(settings)` — so swapping providers (Gemini Live, an Anthropic real-time offering, a self-hosted pipeline) is a config change, not a refactor.

LiveKit deployment defaults to LiveKit Cloud in the dev compose; the production compose includes a self-hosted `livekit/livekit-server` container.

## Consequences

**Positive**

- Vendor-neutral at the framework layer. Swapping the realtime model is a function rewrite, not an architectural one.
- Built-in production features: turn detection, interruption handling, noise cancellation, recording hooks, telephony via SIP.
- Self-hostable end-to-end (LiveKit server is OSS), matching the Supabase + Docker self-host posture.
- Industry default for production voice products in 2025–26 — recognition from any contributor.
- ~50–100ms latency overhead vs OpenAI Realtime direct (acceptable; total TTFA still 500–800ms).

**Negative**

- More moving parts in dev: media server + agent worker + frontend. LiveKit Cloud's free tier sidesteps this for development.
- Larger config surface than direct OpenAI integration.
- Agent dispatch in livekit-agents 1.x is explicit-named; required `agent_name` + `RoomConfiguration.agents` plumbing on every token (see ADR 0005 and `GOTCHAS.md`).

## Alternatives considered

- **OpenAI Realtime direct.** Rejected. Lowest raw latency but locks the template to OpenAI, no recording/observability/telephony, no self-host story. Acceptable for a single-app demo, wrong for a template that downstream apps will customize.
- **Roll-your-own pipeline.** Rejected. Reinventing turn detection, interruption handling, and media-server scaling is months of work for no template-grade win.

## Pointers

- `packages/core/core/realtime.py` — model factory seam.
- `packages/core/core/livekit.py` — token issuance + agent dispatch wiring.
- `apps/agent/agent/session.py` — worker entrypoint.
- `.scratch/voice-ai-template/PRD.md` "Voice and realtime stack" section.
