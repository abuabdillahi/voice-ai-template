# PRD: Sarjy product polish — onboarding, language, interruption, and escalation UX

**Type:** feature on the existing triage product
**Status:** needs-triage
**State:** unscoped — implementation issues to be split out under `.scratch/sarjy-product-polish/issues/` after triage

## Problem Statement

Six rough edges on the existing triage product erode trust the moment a user notices them:

1. **Every session opens with the full disclaimer.** A returning user who has already heard "I am an educational tool, not a doctor" three times listens to it again before the agent can get to the prior-condition fork the recall feature was built to enable. The disclaimer is the load-bearing legal framing for first-time users; for returning users it is friction.
2. **A safety escalation does not visibly end the session.** When the safety screen fires on tier-1 / tier-2 content the agent speaks the scripted message and calls `session.aclose()` — but `aclose()` closes the `AgentSession`, not the LiveKit room. The user's participant remains in the room, the connection-status pill still reads "Connected", and the user is left staring at a UI that looks fine while the agent has gone silent. A user who interprets the silence as a glitch and clicks "Connect" again has missed the routing intent of the escalation entirely.
3. **The agent will respond in any language the user speaks.** OpenAI's realtime model is happily multilingual, but the triage product is scoped to English-language clinical content (the embedded knowledge base, the escalation scripts, the safety regex patterns). A Spanish-speaking user gets a Spanish-language reply that draws from an English knowledge base — the worst of both worlds.
4. **Small noises interrupt the agent mid-sentence.** The default server-VAD thresholds on OpenAI Realtime cut the agent off on coughs, throat-clears, keyboard clicks, and sighs. The user did not intend to take the turn; the agent yielded anyway. This is especially jarring during the disclaimer and the OPQRST opener where the agent is delivering load-bearing content.
5. **The agent has no name.** The product is referred to in the UI as "Ergo Triage" but the agent never identifies itself, so a returning user has no relational anchor — every session is a stranger.
6. **The product brand "Ergo Triage" is being retired in favour of "Sarjy".** The header, banner copy, and component file names still say "Ergo Triage."

## Solution

A coordinated polish pass that fixes all six edges in proportion to their visibility:

- The agent introduces itself as **Sarjy** at the top of every session. First-time users hear `"Hi, I'm Sarjy. [full disclaimer]"`; returning users hear `"Hi, Sarjy here. Quick reminder I'm not a doctor."` followed by the existing prior-condition fork. The shorter refresher drops the scope re-read; the on-screen disclaimer banner continues to carry the visual scope reminder.
- Returning-user detection is keyed off "any prior conversation row exists for this user" — broader than the existing condition-bearing prior-session signal, so a user who connected and dropped before reaching a condition is still recognised as having heard the disclaimer.
- A new `lk.session-end` data-channel topic carries `{reason, tier}` to the frontend before the escalation script speaks. The web client renders a tier-aware end-of-call card (no Reconnect button) and disconnects from its side once the script audio has drained. A server-side room delete remains a fallback in case the frontend misbehaves.
- The realtime model is constructed with `turn_detection={"type": "semantic_vad", "eagerness": "low"}`. Semantic VAD asks the model to judge whether incoming audio is *intent to take the turn* rather than just amplitude over a threshold — coughs and clicks no longer interrupt; a softly-spoken "hold on" still does.
- A new system-prompt rule constrains the agent to English-only replies. On a non-English user utterance the agent says once, in English, "I can only respond in English — could you repeat that in English?". If the user persists, the agent re-states the constraint and stops engaging with the OPQRST flow.
- The product rebrand is a UI surface swap: header text, banner copy, page title, the home component file (`triage-home.tsx` → `sarjy-home.tsx`) and its test references. ADRs, `.scratch/` PRDs, internal module names (`core.triage`, `triage-slots.tsx`, the agent's `triage` tool registry) are preserved — those are engineering nouns, not the product name.

## User Stories

### End user — opening experience

1. As a first-time user of Sarjy, I want the agent to introduce itself by name and read the full educational-tool disclaimer before asking me anything, so that I know what I am talking to and what its limits are.
2. As a returning user of Sarjy who has heard the disclaimer before, I want the agent to skip the full re-read and instead say "Hi, Sarjy here. Quick reminder I'm not a doctor." before getting to the prior-condition fork, so that I am not made to listen to legal framing I have already heard.
3. As a returning user of Sarjy, I want the agent to use phrasing that signals it remembers we have spoken before ("Sarjy here") rather than introducing itself afresh, so that the relationship feels continuous across sessions.
4. As a returning user whose prior session ended without identifying a condition, I want the shorter disclaimer treatment anyway, so that the disclaimer length is keyed to "have I heard this before" rather than "did my last session reach a diagnosis."
5. As a user who can read the on-screen disclaimer banner, I want to hear an audible reminder that the agent is not a doctor on every return visit, so that an eyes-off user is not relying solely on UI they may not be looking at.

### End user — safety escalation visibility

6. As a user whose utterance triggered a tier-1 (emergent) safety escalation, I want the chat UI to clearly indicate the call has ended and to display the escalation routing (e.g. call your local emergency number) in writing, so that I do not interpret the silence as a network glitch and try to reconnect.
7. As a user whose utterance triggered a tier-2 (urgent) safety escalation, I want a tier-appropriate end-of-call message that points me to urgent care today, so that the visible UI reinforces the agent's spoken routing rather than contradicting it with a generic "Disconnected" pill.
8. As a user whose call has ended on a safety escalation, I want there to be no Reconnect button on the end-of-call card, so that I am not nudged back into a tool the safety screen has just routed me away from.
9. As a user whose call has ended on a safety escalation, I want the scripted spoken message to finish playing before the room actually disconnects, so that the audio is not clipped mid-word.
10. As a user, I want the escalation end-of-call card to be reachable even if the frontend signal is dropped, so that a transport hiccup does not leave me stranded with no UI feedback.

### End user — language

11. As a user who speaks English, I want the agent to respond in English — its existing behaviour, unchanged, so that nothing about my experience regresses.
12. As a user who codeswitches into Spanish (or any non-English language) mid-session, I want the agent to politely ask me to repeat the question in English rather than silently translating my Spanish into an English response, so that I know what is happening and am not misled by a translation I cannot inspect.
13. As a user who continues to speak a non-English language after being asked once, I want the agent to re-state the English-only constraint and stop engaging with the OPQRST flow, so that the conversation does not drift into a misrepresented translation loop.
14. As a user, I want the live transcript to show what I actually said in the language I said it, so that the persisted record is faithful to my words even though the agent's reply is constrained to English.

### End user — interruption gating

15. As a user, I want a cough, a sigh, a throat-clear, or a keyboard click not to interrupt the agent's spoken response, so that the disclaimer and OPQRST opener are delivered without being chopped up.
16. As a user, I want to be able to interrupt the agent by speaking — even softly — when I actually want to take the turn, so that I am not stuck listening to a long response I already understood.
17. As a user who is mid-sentence when the agent starts a long reply, I want the agent to yield naturally when I keep speaking, so that the conversation feels like a conversation rather than a script.

### End user — brand

18. As a user landing on the home page, I want to see the product called "Sarjy" in the header and the disclaimer banner, so that the visual identity matches the agent's spoken self-introduction.
19. As a user, I want the browser tab title to read "Sarjy" so that the tab is identifiable when I have several browser tabs open.

### Maintainer — module shape and safety

20. As a maintainer, I want the returning-user signal to be a single boolean derived from a separate, narrowly-scoped query function, so that the disclaimer-branching logic does not get tangled with the existing condition-bearing-prior-session fetch used by the recall feature.
21. As a maintainer, I want `build_triage_system_prompt` to remain a pure function with the new `is_returning_user` flag added as a keyword argument, so that prompt rendering for every combination of (returning, condition-bearing-priors) can be unit-tested without standing up a session.
22. As a maintainer, I want the existing empty-input invariance (no priors AND first-time user → byte-for-byte identical to today's static prompt) preserved exactly, so that the prompt regression anchor for first-time users is not disturbed by the polish pass.
23. As a maintainer, I want the new English-only rule to be a single declarative line in the system prompt rather than a transcription-side `language=en` constraint, so that the live transcript remains faithful to the user's actual words and STT does not garble codeswitched speech.
24. As a maintainer, I want the realtime-model turn detection to be configured at the existing `core.realtime.create_realtime_model` seam rather than at the agent-session call site, so that "how the model decides when the user is speaking" stays a one-line change in one place.
25. As a maintainer, I want the new `lk.session-end` data-channel topic to be a module-level constant in the agent worker alongside the existing `TOOL_CALLS_TOPIC` and `TRIAGE_STATE_TOPIC`, so that all data-channel topic names are co-located and the wire contract is reviewable in one place.
26. As a maintainer, I want the safety-floor close path to retain a server-side room-delete fallback in addition to the new frontend-initiated disconnect, so that a misbehaving or disconnected frontend cannot leave a room open after an escalation.
27. As a maintainer, I want `_wire_end_conversation_on_shutdown` to keep working unchanged, so that conversation summaries and `recall_context` generation still run on escalation-triggered teardown.
28. As a maintainer, I want the rebrand confined to the user-visible UI surface (header, banner, title, home component file + tests), so that ADRs, `.scratch/` PRDs, and internal module names are preserved as historical engineering vocabulary.

### Maintainer — observability

29. As a maintainer, I want a structured log line emitted when an escalation triggers a session-end signal, so that the new code path is observable in production logs alongside the existing `agent.safety.escalation` line.
30. As a maintainer, I want a structured log line emitted when the returning-user disclaimer branch is taken, so that the rate of returning vs. first-time disclaimer rendering is observable without parsing prompts.

## Implementation Decisions

**Returning-user signal — narrow new query.** A new pure-ish function `core.conversations.has_prior_session(user, *, supabase_token) -> bool` runs a `count(1) limit 1` against the `conversations` table for the user. Returns `True` when at least one prior row exists, `False` otherwise. Distinct from the existing `list_recent_with_recall` which filters to condition-bearing rows — the disclaimer signal is intentionally broader. Best-effort: a transient Supabase failure logs a warning and returns `False` (full disclaimer plays — safe default).

**Prompt branching — new keyword argument on `build_triage_system_prompt`.** The existing `build_triage_system_prompt(prior_sessions)` gains an `is_returning_user: bool = False` keyword argument. Branches:

- `is_returning_user=False` and `prior_sessions=[]` → prompt is byte-for-byte identical to today's, plus the new English-only rule and the new Sarjy self-introduction rule. (Empty-input invariance is *modified* once, deliberately, to add the two new rules; this is the new regression anchor for first-time users.)
- `is_returning_user=True` and `prior_sessions=[]` → short refresher rule injected: agent opens with `"Hi, Sarjy here. Quick reminder I'm not a doctor."` and proceeds straight into "Where is the discomfort located?".
- `is_returning_user=True` and `prior_sessions` non-empty → the existing prior-session block from the recall feature is rendered; the opener uses the short Sarjy refresher and then the existing prior-condition fork.

**Self-introduction rules.** Two new rules added to the static prompt section:

- *First-time:* "Open the conversation with `Hi, I'm Sarjy.` immediately before the educational-tool disclaimer."
- *Returning:* "Open with `Hi, Sarjy here. Quick reminder I'm still an educational tool, not a doctor.` before any prior-condition fork."

The phrasing is fixed in the prompt rather than left to the model to compose, so the test suite can assert it verbatim.

**English-only rule.** A new declarative line in the static prompt section (so it applies in every render, returning or not):

> Respond only in English, even if the user speaks another language. Do not translate the user's words into English in your reply; reply as if they had spoken English. If the user speaks a non-English language, say once, in English: "I can only respond in English — could you repeat that in English?". If the user persists in a non-English language, restate the constraint and stop progressing the OPQRST interview until they switch to English.

No transcription-side change. The live `lk.transcription` topic continues to receive the user's words in whatever language they spoke them.

**Realtime turn detection.** `core.realtime.create_realtime_model` passes `turn_detection={"type": "semantic_vad", "eagerness": "low"}` into the OpenAI plugin's `RealtimeModel` constructor. Eagerness is exposed as a module-level constant so a future tuning pass can flip it to `"medium"` without re-reading the surrounding code. **Pre-implementation check:** confirm the installed version of `livekit-agents`'s OpenAI plugin surfaces `turn_detection` as a constructor kwarg; if it does not, fall back to bumped server-VAD thresholds (`threshold=0.7`, `silence_duration_ms=800`, `prefix_padding_ms=300`) and document the regression in the issue.

**Session-end data-channel topic.** A new module-level constant `SESSION_END_TOPIC = "lk.session-end"` is added to `agent.session` alongside `TOOL_CALLS_TOPIC` and `TRIAGE_STATE_TOPIC`. The payload shape is:

```json
{ "reason": "escalation", "tier": "emergent" | "urgent" }
```

`reason` is open for future expansion (e.g. `"out_of_scope"`) but only `"escalation"` is emitted in this PRD's scope. `tier` is the existing `core.safety.RedFlagTier` value rendered as a string.

**Escalation flow rewiring.** Inside the existing `_wire_safety_screen._screen_and_maybe_escalate`:

1. **Before** speaking the script, send the `{reason, tier}` payload on `SESSION_END_TOPIC` so the frontend can render the end-of-call card while the audio is playing.
2. Speak the script via the existing `_speak_escalation_script` helper, unchanged.
3. After the script returns, sleep a brief audio-drain delay (target ~500 ms; tune if escalation tests show clipping) before tearing the room down.
4. Replace the existing `session.aclose()` / `session.close()` call with a server-side `LiveKitAPI.room.delete_room(...)` call as the authoritative teardown — frontend-initiated disconnect still happens first when the frontend is healthy, but the server-side delete guarantees teardown when it is not.
5. The existing `_persist_safety_event` and `_wire_end_conversation_on_shutdown` paths are unchanged — both run on the room close that the new teardown produces.

**End-of-call card.** A new `apps/web/src/components/end-of-call-card.tsx` renders tier-aware copy. Tier-1 (`emergent`) → "Call your local emergency number now." Tier-2 (`urgent`) → "Please seek urgent care today." No Reconnect button. The card replaces the talk page's transcript area for the rest of the page session; clicking the existing Sign-out / History links is the only way out.

**Frontend session-end hook.** A new `apps/web/src/lib/livekit-session-end.ts` exposes `useSessionEndSignal(room: Room | null) -> SessionEndSignal | null`. Subscribes to `lk.session-end` text-stream events on the room, parses each payload, returns the latest. Mirrors the existing `useLivekitTriageState` and `useLivekitTranscript` patterns.

**Talk page wiring.** `talk-page.tsx` calls the new hook; on a non-null signal it renders the end-of-call card in place of the transcript and triggers `room.disconnect()` after a short delay matching the server-side audio-drain window.

**UI rebrand surface.** Confined to:

- `apps/web/src/components/triage-home.tsx` → `sarjy-home.tsx`; component `TriageHome` → `SarjyHome`.
- Header text `"Ergo Triage"` → `"Sarjy"`.
- Disclaimer banner body `"Ergo Triage helps you think about office-strain symptoms…"` → `"Sarjy helps you think about office-strain symptoms…"`.
- `apps/web/index.html` `<title>`.
- Import in `apps/web/src/routes/index.tsx`.
- Test references in `apps/web/src/__tests__/HomeRoute.test.tsx`.

ADRs, `.scratch/` PRDs, the `triage` tool registry, `core.triage`, `triage-slots.tsx`, `TRIAGE_TOOL_NAMES`, `TRIAGE_STATE_TOPIC`, and other internal module names are preserved deliberately — they are engineering vocabulary, not product brand.

**Observability.** Two new structured log lines: `agent.disclaimer.short_branch` (emitted at session start when the returning-user branch is selected, with `user_id` already bound to the logger context); and `agent.safety.session_end_signal_emitted` (emitted when the new topic payload is sent, with `tier` and `reason`).

## Testing Decisions

**What makes a good test here.** All tests target observable external behaviour. For prompt-rendering tests, the assertion is on the rendered string — the verbatim presence of each new rule and the verbatim opener phrasing. For the new query and hook, the assertion is on input/output of a deep, isolated module — no test reaches through to verify which Supabase method was called or which event listener was registered. Tests are written test-first (TDD): the failing test pins the contract before the implementation lands.

**Module: `core.conversations.has_prior_session` (unit, TDD).** The Supabase client is the existing injection seam (`core.supabase.client_for_user`). Tests cover:

1. Returns `True` when the count query yields ≥ 1 row.
2. Returns `False` when the count query yields 0 rows.
3. Returns `False` (with a warning log) when the underlying client raises.
4. Calls the Supabase client with the user's access token, not the service-role key (the existing token-scoping convention used by `list_for_user`).

Prior art: the existing `list_for_user` and `list_recent_with_recall` tests in `packages/core/tests/`.

**Module: `agent.session.build_triage_system_prompt` (unit, TDD).** Pure function. Tests cover:

1. `(is_returning_user=False, prior_sessions=[])` → rendered string contains the literal `"Hi, I'm Sarjy."` rule, the full disclaimer rule, the new English-only rule, and *does not* contain the short-refresher phrasing.
2. `(is_returning_user=True, prior_sessions=[])` → rendered string contains `"Hi, Sarjy here. Quick reminder I'm still an educational tool, not a doctor."` and *does not* contain the full-disclaimer instruction.
3. `(is_returning_user=True, prior_sessions=[<one PriorSession>])` → contains both the short refresher phrasing and the existing "Most recent session" prior-condition block.
4. The English-only rule appears in every branch.
5. The "name the condition, never the numbers" rule (existing, from the recall feature) still appears verbatim in branches 1 and 2 — regression anchor that the polish pass does not erode existing safety rules.
6. The first-time-user-no-priors branch (case 1) is the new regression anchor; once written, it is the reference point any future change must justify modifying.

**Module: `apps/web/src/lib/livekit-session-end.ts` `useSessionEndSignal` (unit, TDD).** A stub `Room` exposes a way to inject `text_stream` events on the topic. Tests cover:

1. Returns `null` before any event is received.
2. Returns `{reason: "escalation", tier: "emergent"}` after a well-formed payload arrives on `lk.session-end`.
3. Ignores events on other topics.
4. Returns `null` (and does not throw) for malformed JSON.
5. Cleans up its subscription on unmount.

Prior art: the existing `useLivekitTriageState` and `useLivekitTranscript` test patterns in `apps/web/src/__tests__/`.

**Skipped — out of unit-test scope.** No dedicated unit tests for the realtime turn-detection kwarg (one-line factory call; integration-test territory). No dedicated unit tests for the rebrand text-swap (snapshot drift on a static string is low-value). No unit test of the safety-screen rewiring end-to-end — covered by extending the existing safety-screen integration test under `apps/agent/tests/` to assert the new topic emission and the room-delete fallback path.

## Out of Scope

- Reconnect-after-escalation flow. Once the safety screen has fired, there is no in-product path back into the triage voice loop on that conversation.
- A configurable disclaimer-shortening threshold (e.g. "show full disclaimer every 5th session"). Two states only: first-time vs. returning.
- Per-user opt-out of the short disclaimer. The on-screen banner remains; the audible refresher is shorter on every return.
- Localising the agent into another language. English-only is enforced and the routing on a non-English user is "ask them to switch", not "switch the agent".
- Localising the on-screen UI strings. The on-screen banner stays English.
- Renaming internal modules / Python packages / ADR titles to drop "ergo" or "triage". Engineering vocabulary is preserved.
- Renaming the `core.triage` slot store, the `TRIAGE_TOOL_NAMES`, the `TRIAGE_STATE_TOPIC`, or the `triage` tool registry.
- Tuning safety-TTS playback volume, voice selection, or pacing. ADR 0007 is not reopened.
- Changing the `core.safety` regex screen, the classifier model, or the escalation script wording. The escalation flow is rewired, not the escalation content.
- Detecting non-English speech via STT-side `language` constraints or a separate language-id model. Language enforcement is prompt-only.
- Server-VAD threshold-tuning as a long-term solution. Semantic VAD is the primary; threshold-tuning is the named fallback if the plugin does not surface the kwarg.
- Persisting "did the user speak a non-English language this session" as a structured field. The transcript already records what was said.

## Further Notes

The single thread tying these six items together is *visible coherence at session edges*. The disclaimer is the front edge; the escalation is the back edge; the self-introduction, the English-only rule, the interruption gating, and the brand all live in the user's first thirty seconds and last thirty seconds of the call. Each item is small in isolation; the value comes from doing them together so the next user who returns has a session that opens, runs, and ends in a way that matches the agent's spoken self-introduction.

The escalation-end signal-then-disconnect pattern is recyclable. A future "out-of-scope routing" feature could emit on the same `lk.session-end` topic with `reason: "out_of_scope"` and a different end-of-call card variant. The PRD's scope is the escalation reason only, but the topic shape and the frontend hook contract are designed to admit that extension without a breaking change.

The "name the condition, never the numbers" safety rule introduced by the recall feature must remain verbatim in the rendered prompt across all branches. The polish pass adds rules around that rule; the test suite explicitly asserts the existing rule is still present after the changes. Drift in the rule's wording is the failure mode that re-opens the hallucination risk the original disposition was guarding against.

Semantic VAD's behaviour at `eagerness: "low"` should be sanity-checked against a realistic conversation in staging before merging — the plugin and the OpenAI Realtime model both evolve, and the lowest-eagerness setting is the point furthest from the default. If users report the agent feels sluggish to yield, the next step is `"medium"`, not back to server-VAD.
