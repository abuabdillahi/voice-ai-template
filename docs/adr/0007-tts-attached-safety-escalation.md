# ADR 0007: TTS-attached safety escalation, shared voice across realtime + TTS

Status: Accepted (2026-05-05)
Supersedes: —

## Context

The triage agent runs on OpenAI's `gpt-realtime` model — a speech-to-speech LLM that transcribes user audio and produces assistant audio in a single duplex stream. There is no separate TTS pipeline.

The safety screen (`agent.session._wire_safety_screen`) fires on every committed user utterance. Tier-1 (`emergent`) and tier-2 (`urgent`) hits must play a versioned scripted message verbatim — the wording is reviewed against guidance in `core.safety._ESCALATION_SCRIPTS`, recorded in the `safety_events` audit log, and exists precisely so the spoken language at escalation is not the model's own.

The first cut routed the script through `AgentSession.say(script)`. In realtime mode `say()` raises with "no TTS model attached" because the realtime model has no separate TTS. The fallback was `session.generate_reply(instructions="speak this verbatim: <script>")`. That path failed in three independent ways:

1. **Race with the in-flight reply.** By the time the safety classifier resolves, the realtime model has typically already started its own auto-reply for the triggering user turn. Submitting `response.create` while one is in progress returns `conversation_already_has_active_response` from OpenAI Realtime, then the LiveKit-side wait times out.
2. **Paraphrase risk.** `generate_reply(instructions=...)` is a soft constraint. The model usually obeyed but sometimes paraphrased — a problem when the spoken wording is the load-bearing safety property and the audit log records the canonical script.
3. **Audio playout vs. session close.** Even when the script reached the model, our `aclose()` after `await maybe` did not consistently wait for the audio to finish reaching the client.

Independently, the realtime model and the OpenAI standalone TTS API have **non-identical voice catalogues**:

| Voice                                           | `gpt-realtime` | `gpt-4o-mini-tts` |
| ----------------------------------------------- | :------------: | :---------------: |
| alloy, ash, ballad, coral, sage, shimmer, verse |       ✓        |         ✓         |
| marin (realtime default), cedar                 |       ✓        |         ✗         |
| echo, fable, onyx, nova                         |       ✗        |         ✓         |

Realtime-only voices (`marin`, `cedar`) are not addressable on `/v1/audio/speech` at all, on any of the three exposed model variants (`tts-1`, `tts-1-hd`, `gpt-4o-mini-tts`).

## Decision

**Attach an OpenAI TTS to the AgentSession at construction.** `core.realtime.create_safety_tts(settings, voice=...)` builds a `gpt-4o-mini-tts` instance; `agent.session.build_session` passes it to `AgentSession(llm=..., tts=...)`. With a TTS attached, `AgentActivity.say` resolves `self.tts` to the session TTS and uses the standard `_tts_task` path — no realtime collision, no paraphrase, exact-script playback.

**`_speak_escalation_script` is `interrupt → say`.** The realtime model's in-flight auto-reply is cancelled via `session.interrupt()` (which sends `response.cancel` on the realtime websocket and waits for current speech to drain) before the scripted `say()` is dispatched. Without this, the realtime audio overlaps the TTS audio. The `generate_reply(instructions=...)` fallback is deleted entirely.

**A single voice is threaded through both factories.** `build_session(voice=...)` resolves `voice=None` to `core.realtime.DEFAULT_VOICE` and passes the same value to `create_realtime_model` and `create_safety_tts`. The default lives in the **overlapping catalogue** so both factories accept it. **`DEFAULT_VOICE = "sage"`** — chosen after listening: `coral` was the first pick (warm, conversational, closest to `marin` on paper) but sounded harsh on the actual Realtime renderer; `sage` is calm, balanced, gender-neutral, and acceptable on both sides.

**`agent.safety.script_spoken` info log** is emitted immediately after `say()` returns, with the tier on it. Without that anchor the only timeline marker for the spoken script is the `livekit.plugins.openai.tts.TTS` metric, which lives on a different logger and is awkward to correlate with `agent.safety.escalation`.

## Consequences

**Positive**

- Exact-script playback. The spoken wording matches `core.safety._ESCALATION_SCRIPTS` and the `safety_events` row.
- Deterministic timing. No collision with the in-flight realtime response, no `conversation_already_has_active_response`, no `generate_reply timed out`.
- Single voice across the conversation. The safety alert no longer sounds like it comes from a different system.
- One observable event marks the spoken script in the application log.

**Negative**

- The realtime-exclusive voices (`marin`, `cedar`) are off-limits as the everyday voice. Any voice the everyday session uses must also exist on `/v1/audio/speech`.
- An OpenAI TTS dependency is loaded for every session even though only the rare safety escalation uses it. The cost is the TTS plugin's import + a small client-init footprint; no API call is made unless `say()` runs.
- A future fork that wants a richer voice library (`marin`-tier voices specifically, or non-OpenAI voices) has to either (a) switch the TTS plugin to a vendor with broader catalogue, or (b) revert to the realtime-only path and accept paraphrase risk.

## Alternatives considered

- **Keep `generate_reply(instructions=script)` with `interrupt()` first.** Rejected. Solves the race but not paraphrase or audio-playout-vs-close. Audit-log integrity is the load-bearing property of the safety path; sacrificing it to avoid one dependency is the wrong trade.
- **Switch to a full STT + LLM + TTS pipeline (drop `gpt-realtime`).** Rejected. End-to-end latency goes from 200–400 ms TTFT to 600 ms–1.2 s, and the realtime model's paralinguistic understanding (distress, hesitation in voice) matters more for triage than for most agents. Large rewrite for a small edge-case win.
- **Use a non-OpenAI TTS plugin (ElevenLabs / Cartesia / PlayHT).** Rejected for now. Buys access to a much larger voice library — including voices closer to `marin` in tone — but adds a vendor, credentials, latency budget, and failure mode for a feature that only fires on safety alerts. Worth revisiting if voice character becomes a product-level concern.
- **Pre-record the escalation script audio with `marin` and ship as static files.** Rejected. The script is versioned alongside code and changes occasionally; baking audio adds a build step and a synchronisation footgun.
- **Default to `coral`.** Tried first, rejected by ear. `sage` won the listening test.

## Pointers

- `packages/core/core/realtime.py` — `create_realtime_model`, `create_safety_tts`, `_DEFAULT_VOICE = "sage"`, `DEFAULT_VOICE` (public alias).
- `apps/agent/agent/session.py` — `build_session` (resolves the shared voice and wires both factories), `_speak_escalation_script` (`interrupt → say` plus `script_spoken` log), `_wire_safety_screen` (the regex + classifier hook that calls into the script).
- `packages/core/core/safety.py` — `_ESCALATION_SCRIPTS`, `escalation_script_for`. Canonical wording lives here.
- `packages/core/core/safety_events.py` — `safety_events` audit row writer.
- `apps/agent/tests/integration/test_session_safety.py::test_realtime_escalation_interrupts_then_says_script` — pins the `interrupt → say` ordering and the `script_spoken` log line.
- `apps/agent/tests/unit/test_session.py::test_build_session_passes_same_voice_to_realtime_and_tts` and `::test_build_session_default_voice_overlaps_both_catalogs` — pin the shared-voice contract.
