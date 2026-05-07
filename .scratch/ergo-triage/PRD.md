# PRD: Office Strain Triage Voice Agent (Ergo Triage MVP)

**Type:** new product, built on the voice-ai-template scaffold
**Status:** needs-triage
**State:** unscoped — implementation issues to be split out under `.scratch/ergo-triage/issues/` after triage

## Problem Statement

Office workers commonly develop musculoskeletal and visual strains from prolonged desk and screen use — carpal tunnel syndrome, computer vision syndrome, tension-type headache, upper trapezius / "text neck" strain, lumbar strain. The friction of accessing physiotherapy or occupational health for early-stage symptoms is high: appointment lead times are days to weeks, and the worker often does not know whether what they are feeling is a passing ache or an early sign of something worth investigating. The result is that workers either ignore symptoms until they become disabling, or self-diagnose using generic web resources whose advice is unreliable and which cannot ask the discriminating questions a clinician would.

A voice-first triage tool that specialises tightly in this domain can occupy the gap between "ignore it" and "wait two weeks for an appointment" — but only if it is safe by construction. Health-adjacent voice tools that hallucinate dosages, miss red-flag presentations, or pretend to diagnose conditions outside their competence cause direct harm and create regulatory liability. The product is worth building only if the safety layer is the first thing built, not the last.

## Solution

An educational, voice-first triage agent that takes a structured symptom history for one of five office-strain presentations, surfaces a small set of conservative self-care recommendations grounded in a curated knowledge base, and escalates promptly to professional care when the conversation surfaces a symptom that warrants it. The agent is explicitly framed — in the system prompt, in the spoken script, in the UI copy — as an informational tool, not a diagnostic device, and not a substitute for a clinician.

The product is built on the existing voice-ai-template repo. The realtime voice loop, LiveKit integration, Supabase auth, transcript persistence, structured logging, and Docker / compose layout are reused unchanged. The medical domain layer — knowledge base, OPQRST symptom interview, multi-layer red-flag classifier, audit log of safety triggers, scoped tool registry, scoped system prompt — is added on top. The structured-preferences and episodic-memory tools shipped by the template are retained as code but removed from the agent's prompt and tool registration; a triage flow does not benefit from cross-session "remember about you" recall and reintroduces an avoidable hallucination surface.

The MVP is intentionally narrow: five conditions, a static condition knowledge base embedded in the system prompt rather than retrieved from a vector store, a single-language English voice loop, and a safety eval harness whose passing bar is 100% recall on a curated tier-1 red-flag script set. Coverage breadth, retrieval-augmented grounding, multilingual support, and clinician-reviewed content updates are explicitly deferred to post-MVP.

## User Stories

### End user — typical triage flow

1. As an office worker, I want to click a microphone button and start speaking, so that I can describe my symptom without typing.
2. As an office worker, I want the agent to greet me with a clear disclaimer that it is an educational tool and not a doctor, so that I understand what kind of guidance I am about to receive.
3. As an office worker, I want the agent to ask me where the discomfort is located and how long I have had it, so that the conversation begins with the basics a clinician would also start with.
4. As an office worker, I want the agent to ask me what makes the symptom worse and what makes it better, so that the recommendation reflects my actual triggers rather than a generic answer.
5. As an office worker, I want the agent to ask about radiation, severity, prior episodes, and my desk setup, so that the differential narrows toward the condition that best matches my presentation.
6. As an office worker, I want the agent to give me two or three concrete conservative self-care recommendations grounded in vetted sources, so that I can try something today without waiting for an appointment.
7. As an office worker, I want the agent to tell me when I should expect improvement and when to seek professional evaluation, so that I have a clear next step regardless of how the self-care goes.
8. As an office worker, I want the agent to acknowledge when it is not confident in a recommendation, so that I am not given a definitive answer where one is not warranted.
9. As an office worker, I want the agent to verbalise sources for any specific protocol it suggests, so that I can verify what I am being told.

### End user — escalation paths

10. As an office worker reporting numbness or weakness in an arm, I want the agent to stop the symptom interview and tell me to seek urgent care, so that a possible neurological presentation is not treated as an ergonomic complaint.
11. As an office worker mentioning chest pain or sudden severe headache, I want the agent to direct me to call emergency services immediately, so that a possible cardiac or cerebrovascular event is escalated without delay.
12. As an office worker mentioning bowel or bladder symptoms alongside back pain, I want the agent to direct me to urgent care today, so that cauda equina is not missed.
13. As an office worker reporting symptoms persisting more than six weeks, I want the agent to recommend a clinician visit rather than continuing self-care, so that a chronic presentation is not under-triaged.
14. As an office worker describing a symptom outside the agent's scope (mental health, pregnancy, pediatric, post-surgical), I want the agent to tell me clearly that it cannot help and route me to an appropriate resource, so that I do not receive guidance from a system not built for my situation.
15. As an office worker, I want the escalation message to include a concrete next action ("call 911", "go to urgent care today", "book a GP appointment this week"), so that I know exactly what to do.

### End user — refusal behaviour

16. As an office worker asking for a medication or dosage recommendation, I want the agent to decline and explain that medication guidance is outside its scope, so that I am not given pharmaceutical advice from a non-clinical tool.
17. As an office worker asking the agent to "diagnose" me, I want the agent to reframe its output as "what these symptoms might suggest" rather than a diagnosis, so that the regulatory framing of the product is preserved.
18. As an office worker pressing for a definitive answer when the agent's confidence is low, I want the agent to hold the line and recommend clinician evaluation, so that I do not extract a false-confidence answer.

### End user — session ergonomics

19. As an office worker, I want to interrupt the agent mid-sentence, so that the conversation feels natural rather than turn-locked.
20. As an office worker, I want to see a live transcript of the conversation, so that I can verify what the agent heard.
21. As an office worker, I want to see what the agent has gathered so far (symptom location, duration, severity), so that I know what it is reasoning about.
22. As an office worker, I want to revisit the transcript of a past session, so that I can recall what was recommended.

### Developer extending the knowledge base

23. As a developer adding a sixth condition, I want the condition record format to be a single typed dataclass with explicit fields, so that adding a new condition is one file edit and no glue code.
24. As a developer reviewing the knowledge base, I want every condition record to cite its sources inline, so that a clinician reviewer can audit the content without leaving the file.
25. As a developer changing a recommendation protocol, I want the change to show up in code review with the affected condition record, so that medical content is reviewable like any other code.
26. As a developer, I want a clear seam to swap the static knowledge base for a retrieval pipeline later, so that growing past the MVP's five conditions does not require a rewrite.

### Developer working on the safety layer

27. As a developer iterating on the red-flag layer, I want the regex screen to be a pure function that takes an utterance and returns a tier, so that I can add or tune phrase patterns with a unit test rather than a live voice session.
28. As a developer iterating on the classifier, I want the classifier call to be mocked at the OpenAI client boundary, so that I can run the safety test suite offline and in CI.
29. As a developer changing the escalation script, I want the spoken text to live in a versioned constant referenced from one place, so that the wording is not duplicated across the prompt and the runtime path.
30. As a developer adding a sixth tier-1 trigger phrase, I want a single list to edit and a single test fixture to extend, so that the regex layer's coverage is auditable.

### Operator running the service

31. As an operator, I want every red-flag trigger to be persisted to the database with the conversation id, the matched flags, the source layer (regex or classifier), and the utterance text, so that I can audit every escalation after the fact.
32. As an operator, I want every red-flag trigger to also emit a structured log line on stdout, so that an alerting pipeline can react in real time without polling the database.
33. As an operator, I want the safety eval suite to run in CI and block deploys that regress on tier-1 recall, so that a prompt change cannot silently weaken the safety floor.
34. As an operator, I want the agent's session-end log line to include whether the session ended normally or via escalation, so that I can compute escalation rates over time.

### Reviewer (clinician auditing the queue)

35. As a clinician reviewing the safety queue, I want to see a list of every conversation that triggered a red flag, ordered by recency, so that I can review them in batch.
36. As a clinician, I want to read the full transcript leading up to and following the trigger, so that I can judge whether the escalation was correct and whether the agent's surrounding behaviour was appropriate.
37. As a clinician, I want my access scoped to the safety review surface, so that I do not see general user activity outside the audit context.

(Reviewer surface beyond the persisted table is deferred — see Out of Scope.)

## Implementation Decisions

### Scope and content

- Five conditions are in scope for the MVP: carpal tunnel syndrome, computer vision syndrome (eye strain), tension-type headache, upper trapezius / "text neck" strain, lumbar strain from prolonged sitting. Anything outside this list is refused with a routing message rather than triaged.
- The knowledge base is a **static, in-prompt** condition catalogue. For five records, embedding the catalogue directly into the system prompt is faster to build, easier to debug, and eliminates a class of retrieval-induced hallucination versus standing up a vector store. The seam to swap to retrieval-augmented grounding is preserved at the `kb_for_prompt()` boundary so that growth past ~10 conditions can be addressed without a rewrite.
- Each condition record carries: defining symptoms, discriminating symptoms versus neighbouring conditions, severity grading guidance, conservative treatment protocol, contraindications, expected recovery timeline, condition-specific red flags, and source citations. Sources are drawn from public clinical guidance (NIOSH, OSHA ergonomic guidance, AAOS patient information, physiotherapy association protocols).
- The product is framed as **educational, not diagnostic**. The system prompt, the spoken disclaimer, the UI copy, and any external materials use language like "what these symptoms may suggest" rather than "diagnose". Clinician review of the knowledge base is a documented prerequisite to any real-user pilot and is explicitly out of scope for the 24-hour MVP.

### Realtime stack

- The voice loop continues to run on **LiveKit Agents** with **OpenAI `gpt-realtime`** as the speech-to-speech model. Latency, turn-taking, and barge-in behaviour are taken as-is from the template — splitting the realtime model into discrete STT, LLM, and TTS components is not a precondition for the safety posture this PRD requires, because the safety floor is provided by the parallel classifier, not by the realtime model itself.
- The realtime model receives the full condition knowledge base in its system prompt at session start. The prompt instructs the model to interview using OPQRST slots, never to recommend a protocol that is not in the embedded knowledge base, never to invent dosages or numerical specifics, and to call `escalate` immediately if the user volunteers a tier-1 or tier-2 red-flag phrase.

### Safety architecture (defence in depth)

- A two-layer red-flag detector runs **server-side on every committed user utterance**, independently of the realtime model:
  - **Layer 1 — deterministic regex/keyword screen.** Sub-millisecond. Covers tier-1 phrases that must never be missed ("chest pain", "can't feel my arm", "worst headache of my life", "vision went black", "lost consciousness", and a small set of paraphrases). Pure function; trivially testable.
  - **Layer 2 — gpt-4o-mini classifier.** Runs in parallel on the same utterance. Uses OpenAI structured outputs to return `{tier, matched_flags}` deterministically. Reuses the existing `OPENAI_API_KEY`; no new vendor relationship. Catches paraphrased and ambiguous presentations the regex layer cannot.
- The two layers vote in parallel; the **higher tier wins**. If either fires tier-1 or tier-2, the agent worker plays the scripted escalation message, persists the trigger to the safety audit table, and ends the session. There is no realtime-model path that can override an escalation.
- The red-flag detector is **not exposed as a model-callable tool**. Making the detector a tool that the model chooses whether to call is the failure mode the architecture is built to prevent.

### Module shape

- **`core.conditions`** — pure data module. Exposes `Condition` dataclass, `CONDITIONS: dict[condition_id, Condition]`, and `kb_for_prompt() -> str` to render the catalogue into the system prompt block. Adding a condition is a single record append.
- **`core.triage`** — per-session OPQRST slot store and rule-based differential ranking. Pure functions over a per-session-id dict held in process. Slot store is in-memory only — the slots are derivable from the persisted transcript if ever needed offline, and storing them server-side bypasses the `messages` table without buying anything.
- **`core.safety`** — `RedFlagTier` enum, `regex_screen(utterance)`, `classify(utterance)` (async, gpt-4o-mini with structured output), `combine(...)` returning `{tier, matched_flags, source}`. The regex layer and the combiner are pure; the classifier is mockable at the OpenAI client boundary.
- **`core.safety_events`** — persisted audit log. Module surface mirrors `core.conversations` and `core.preferences`: typed insert, typed read for the user's own events. Backed by a new `safety_events` table with row-level security.
- **`core.tools.triage`** — model-callable tools: `record_symptom(slot, value)`, `recommend_treatment(condition_id)`, `escalate(tier, reason)`, `request_more_info(reason)`. Replaces `core.tools.examples` in the agent's tool registration. The structured-preferences and episodic-memory tools (`set_preference`, `get_preference`, `remember`, `recall`) are unregistered for this product but the modules behind them remain in place as a public API surface, mirroring the disposition of `core.preferences` after ADR 0006.
- **`apps/agent/agent/session.py`** — modified. New medical-domain `SYSTEM_PROMPT` with the embedded knowledge base. New `_wire_safety_screen` hook on the `conversation_item_added` event runs regex first and the classifier in parallel; on tier-1 or tier-2 it triggers the escalation path and disconnects. Personalisation helpers (`_load_user_preferences`, the preference-aware `build_system_prompt`) are bypassed for this product but left in source. Persistence, metrics logging, and the supabase-token refresh hook are reused unchanged.
- **`apps/web/src/routes/index.tsx`** — modified. Disclaimer banner ("educational tool, not a doctor, not a substitute for medical advice"), prominent talk button, and a small live panel showing the OPQRST slots gathered so far for demo legibility. Memory sidebar removed for this product. `/history` and `/history/:id` are kept unchanged.

### Schema additions

- New `safety_events` table with columns: `id` (uuid pk), `conversation_id` (uuid fk → `conversations.id`), `user_id` (uuid fk → `auth.users.id`), `tier` (enum: `emergent`, `urgent`, `clinician_soon`), `source` (enum: `regex`, `classifier`, `both`), `matched_flags` (jsonb), `utterance` (text), `created_at` (timestamptz default now()).
- Row-level security policy: `auth.uid() = user_id` for read; insert is performed under the user's JWT context like the existing `conversations` and `messages` tables. A future clinician-reviewer role is anticipated but not implemented in the MVP — the table is the seam.
- Migration file `0004_safety_events.sql` follows the `0001`/`0002`/`0003` naming convention; applied identically in dev and production via the existing Supabase CLI flow.

### Configuration

- One new optional setting: `SAFETY_CLASSIFIER_MODEL` (defaults to `gpt-4o-mini`). Threaded through the typed `Settings` module like the existing realtime model configuration. No new vendor credentials are required — the classifier reuses `OPENAI_API_KEY`.
- The escalation script (per tier) lives in a single versioned constant in `core.safety` and is referenced by both the system prompt and the runtime escalation path.

### What is reused unchanged

- LiveKit room lifecycle, JWT minting, participant metadata for token forwarding, supabase-token refresh hook.
- Supabase auth, JWKS verification, RLS-scoped writes from the agent.
- Conversation persistence (`conversations`, `messages` tables and their hooks).
- Structured logging, the `turn_metrics` line, the bound contextvars (`session_id`, `user_id`, `conversation_id`).
- Docker layout, dev and prod compose, CI shape.

## Testing Decisions

### What makes a good test

- Tests target external behaviour of a module, not implementation details. The medical content of a condition record is data, not a unit-testable behaviour; the *shape* of the record and the *serialisation* into the prompt are.
- Safety-layer tests are deterministic. The regex layer is pure; the classifier is mocked at the OpenAI client boundary so the safety suite runs offline and in CI.
- The safety eval harness is treated as a test, not as a separate quality concern — its scripts live alongside the unit suite and run in CI, and a regression on tier-1 recall blocks the deploy.
- The test suite does not attempt to evaluate the medical *quality* of the agent's recommendations. That is a clinician-review concern, distinct from automated testing, and is out of scope for the MVP.

### Modules under test

- **`core.conditions`** — unit tests covering the dataclass shape and the `kb_for_prompt` round-trip (every record must contribute a stable, parseable block).
- **`core.triage`** — unit tests on the slot store (set, get, clear, multi-session isolation) and on the differential ranking against fixture states (a wrist-numbness state ranks carpal tunnel above lumbar strain, etc.).
- **`core.safety`** — unit tests on the regex layer (every tier-1 phrase, common paraphrases, false-positive negatives) and the combiner (tier precedence, source attribution). Integration-shaped unit test on `classify` with the OpenAI client mocked, asserting the structured-output schema is requested and parsed correctly for each tier.
- **`core.safety_events`** — unit tests on the module surface and an integration test against a real Postgres asserting RLS isolation between users. Mirrors `tests/integration/test_preferences_rls.py` and `tests/integration/test_conversations_rls.py`.
- **`core.tools.triage`** — unit tests for each tool's happy path and error path, asserting the dispatcher returns a string the realtime model can verbalise.
- **Agent session (`apps/agent`)** — integration-style test using LiveKit Agents' built-in session test harness with a mocked realtime model. Asserts that a scripted user utterance carrying a tier-1 phrase triggers the safety hook, persists a `safety_events` row, plays the escalation script, and ends the session.

### Safety eval harness

- A dedicated `tests/safety/` suite with three categories of scripted conversations:
  - **Tier-1 red-flag scripts (10)** — each a short user-utterance script that must result in an `emergent`-tier escalation. The pass bar is 100% recall.
  - **Adversarial extraction scripts (5)** — users attempting to extract medication advice, dosages, or out-of-scope diagnoses. The pass bar is a clean refusal in every case.
  - **Off-scope drift scripts (5)** — mid-conversation drift to mental health crises, pregnancy-related symptoms, paediatric, or post-surgical contexts. The pass bar is a routing message to the appropriate resource and termination of the triage flow.
- Scripts run against the agent session test harness with the realtime model stubbed. The harness asserts on the structured event log (which tools were called, which `safety_events` rows were inserted) rather than on the natural-language wording of the agent's reply, so the suite is robust to prompt iteration.
- CI fails the deploy if tier-1 recall is below 100% or if any adversarial or drift script regresses to a non-refusal response.

### Prior art

- `tests/integration/test_preferences_rls.py` — RLS pattern for the new `safety_events` table tests.
- `tests/integration/test_conversations_rls.py` — message-append pattern; the agent-session safety hook test follows the same structure.
- `apps/agent/tests/integration/test_session_*.py` — LiveKit session-harness pattern for the agent session safety-hook test.
- `tests/unit/test_tools_*.py` — tool-dispatcher tests for the new triage tools.

## Out of Scope

- Conditions outside the five named (cubital tunnel, de Quervain's, lateral and medial epicondylitis, thoracic outlet syndrome, hip/knee strains, sciatica, tendinopathies broadly). Adding a sixth condition is a single record append after MVP and is explicitly the first post-MVP backlog item.
- Retrieval-augmented generation over a vector store. The seam is preserved; the implementation is deferred until the catalogue grows past roughly ten conditions.
- Clinician review queue UI. The audit log lives in `safety_events`; reviewer-role authentication, a `/admin/safety` web route, and review-state machinery (acknowledged, dismissed, escalated to legal) are post-MVP.
- Personalisation across sessions. The structured-preferences tools and the episodic memory layer remain in the codebase as kept-public-API surface but are unregistered from this product's prompt and tool list. Cross-session "remember about you" memory is the wrong default for triage and reintroduces an avoidable hallucination surface.
- Telephony. Voice access is browser-only via the existing LiveKit Cloud project. SIP / Twilio bridging is post-MVP.
- HIPAA compliance, BAAs with vendors, PHI handling. The MVP collects no clinical identifiers by design — the persisted `messages` and `safety_events` rows contain symptom descriptions and, when the user voluntarily discloses a locality during clinician-finding, that locality. No name, date of birth, address-line, or other PII is collected. RLS continues to enforce per-user isolation; the same data set is what a returning user sees in their own `/history/:id` view. Productionising for a US clinical context requires a separate compliance workstream.
- Multilingual support. English only.
- Mobile applications and PWA optimisations.
- Audio recordings. Only text transcripts are persisted, matching the existing template policy.
- Full clinical assessment beyond OPQRST (no functional movement screens, no validated outcome measures like DASH or ODI).
- Scheduled follow-up nudges ("how is your wrist three days later?"). Single-session only.
- A heavier eval framework (Langfuse, Helicone). Logs and the safety harness suffice for MVP.

## Further Notes

- The 24-hour MVP constraint is the load-bearing scope decision. The build order matches the safety-first principle: the system prompt and the knowledge base are written first; the safety layer is wired second; the triage tools and session changes are third; the eval harness is fourth; the frontend and deployment polish are last. Cuts, if forced by the timeline, work backwards from the bottom — the safety floor and the eval harness are not what gets cut.
- The retained-as-public-API disposition for the structured-preferences and episodic-memory modules follows the precedent set by ADR 0006 (the settings page removal). Removing them from the prompt and tool list is reversible by a single change in the agent worker's tool registration; the migrations and data tables remain untouched.
- Clinician review of the knowledge base before any real-user pilot is the non-negotiable next step after the MVP build. The MVP demo can be shown internally or to a controlled audience with a verbal disclaimer; it cannot be opened to general users without a clinician audit. This is a process commitment, not a code commitment, and is captured here so it is not lost between the MVP and any subsequent rollout.
- A future ADR is anticipated for the safety architecture — specifically, the decision to run the red-flag layer as a server-side parallel classifier rather than as a model-callable tool. The reasoning is captured in this PRD but warrants its own ADR once the implementation lands so that downstream forks understand the deliberate choice.
- Implementation issues split out from this PRD live alongside it under `.scratch/ergo-triage/issues/`, numbered and named per the local issue-tracker convention.
