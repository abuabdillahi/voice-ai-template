# Sarjy — UI/UX design brief for Claude Design

## Your task

Design the UI and UX for **Sarjy**, a voice-first triage assistant for office-strain symptoms. Produce wireframes / hi-fi mockups for every screen described below, plus a design rationale per screen. Where the current UX has problems, propose specific fixes — don't just re-skin what's there.

The codebase already uses **shadcn/ui** (default style, slate base, CSS variables) and **Tailwind CSS** (Tailwind v4 via `@import 'tailwindcss'`). Stay within the shadcn vocabulary — Card, Button, Badge, Collapsible, Form, Input, Select, Label — and extend with additional shadcn primitives (Dialog, Tabs, Sheet, Toast, Tooltip, Skeleton, Avatar, Progress, etc.) where they earn their keep. Don't invent a new design system.

## What Sarjy is

Sarjy is an **educational, voice-first triage tool** for five specific office-strain conditions:

1. Carpal tunnel syndrome
2. Computer vision syndrome (digital eye strain)
3. Tension-type headache
4. Upper trapezius / "text neck" strain
5. Lumbar strain from prolonged sitting

It is explicitly **not a doctor**. The product walks the user through OPQRST-style symptom triage (Onset, Provocation, Quality, Region, Severity, Time — adapted) by voice, then either (a) suggests a self-care routine, or (b) escalates to a clinician via a `find_clinician` tool that returns nearby providers from OpenStreetMap, or (c) ends the session with an emergent/urgent routing message ("call your local emergency number now" / "seek urgent care today").

The voice loop runs over **LiveKit + OpenAI Realtime**. The user clicks Connect, unmutes their mic, and talks. The agent transcribes both sides, emits structured triage state (which OPQRST slots have been filled), and streams tool-call results into the page in real time.

Anything outside the five in-scope conditions — medications, mental health, pregnancy, paediatric, post-surgical — is routed away. The product has a deliberately narrow scope and the UI must communicate that scope before the user starts talking.

## Tech context (so your designs map to what's buildable)

- **Framework:** Vite + React + TanStack Router (file-based routing).
- **Component library:** shadcn/ui (already wired). Tailwind v4 with HSL CSS variables (`--background`, `--foreground`, `--primary`, `--muted`, `--accent`, `--destructive`, `--border`, etc.). Light mode only today; dark mode is a stretch goal — design for light first, but pick variables that translate.
- **Auth:** Supabase email/password. No SSO yet.
- **Realtime:** LiveKit room. UI subscribes to three data topics — `lk.transcription` (utterances), `lk.tool-calls` (tool dispatch + result), `lk.triage-state` (full OPQRST snapshot per turn), plus a session-end signal carrying a tier (`emergent`, `urgent`, `routine`).
- **Brand:** logo is a five-line "equalizer" mark in teal (`#0d9488`) with an amber dot (`#fbbf24`). Wordmark is "Sarjy". Use this palette as a starting point — propose a fuller palette in your brief if you want.

## Current screens (and their problems)

### 1. `/sign-in` — auth screen

**What it does today:** Email + password form in a single Card, centered on the viewport. Toggle link at the bottom switches between "Sign in" and "Create account" modes. No password reset, no email verification flow surfaced, no SSO, no "show password" affordance, no marketing context — a user landing here cold has no idea what Sarjy is before they sign up.

**Problems:**

- The user has to commit to an account before learning what the product does. There is no landing/marketing surface.
- "Don't have an account? Sign up" is a text link buried under the submit button; sign-up should be a peer call-to-action, not an afterthought.
- Errors and success messages render as inline paragraphs with no visual weight — easy to miss.
- The sign-up confirmation message ("Account created. Check your inbox…") doesn't explain whether email verification is even required.

### 2. `/` — home / talk page (the primary surface)

**What it does today:** A vertically stacked single-column page at `max-w-3xl`:

1. Page header: Sarjy logo + wordmark on the left, "History" link + "Sign out" button on the right.
2. **Disclaimer banner** — amber card with "This is an educational tool, not a doctor." plus emergency-routing copy.
3. **Scope statement** — muted card listing the five in-scope conditions and naming the out-of-scope categories.
4. **Talk card** — title "Talk to the assistant", description "Click connect, then unmute to start talking.", Connect / Disconnect button, Mic on/off toggle, status pill (Idle / Connecting / Connected / Disconnected).
5. **"What I've gathered" card** — OPQRST slot table with 10 rows (Location, Onset, Duration, Quality, Severity, Aggravators, Relievers, Radiation, Prior episodes, Desk / context). Empty rows show "not yet disclosed" in italic muted text.
6. **Transcript card** — live-updating list of utterances (user / assistant bubbles) interleaved with tool-call entries. Tool calls are collapsible blocks showing arguments and result as `<pre>` JSON. The `find_clinician` tool gets a special-cased card with a list of nearby clinics (name, address, phone as `tel:` link, distance, OSM map link, ODbL attribution).

When the agent ends the session, the entire talk page is replaced by a single **end-of-conversation card** (amber) with tier-aware routing copy. There is no Reconnect affordance — by design, since the safety screen has just routed the user away from the tool. The only way out is the page chrome (Sign out / History).

**Problems — these are the ones that matter most:**

- **No idle-state encouragement.** Before connecting, the talk card just says "Click connect, then unmute to start talking." A first-time user has no preview of what a Sarjy conversation feels like — no example prompts, no "here's how this works in 30 seconds", no sense of how long a session takes.
- **Two-step start is a friction tax.** "Connect" then "Unmute" is two clicks for one user intent ("talk to the assistant"). Users who miss the unmute step think the product is broken because the agent appears connected but can't hear them. Consider whether Connect should auto-enable the mic on first use, with a permission preflight.
- **The page is a single scrolling column when it doesn't need to be.** On desktop, the OPQRST card and the transcript card both want to be visible during a session. Today the user has to scroll. On a wide viewport this is wasted real estate.
- **Transcript is the hero, but it's third on the page.** During an active conversation, the live transcript is what the user looks at — but it sits below the controls and the OPQRST table, so on smaller screens it scrolls off the bottom.
- **Tool-call entries are noisy.** The `find_clinician` card is well-designed and clearly belongs inline. But generic tool calls render as collapsible JSON `<pre>` blocks tagged "tool" — that's developer-facing chrome leaking into a consumer surface. Either hide these from end users or design a friendlier representation.
- **Status pill is buried.** "Connecting…" sits in the corner of the talk card header. When the connection fails or stalls, users miss it. Connection state is high-stakes here (a broken mic = a broken product) and deserves more weight.
- **No "I'm thinking" / "I'm speaking" indicator for the agent.** The transcript shows what was said _after_ it was said. In voice UX, the user needs to know whether the agent is listening, thinking, or speaking _right now_ — silence is ambiguous.
- **No way to interrupt or rephrase.** Voice users sometimes want to say "wait, scratch that" with a button, especially if they coughed mid-answer. There is no UI affordance for it.
- **OPQRST card is information-dense and static-looking.** Empty rows say "not yet disclosed" in italic muted text — passive. A progress feel ("3 of 10 gathered") and a visual emphasis on the _next_ slot the agent is likely to ask about would make the surface feel alive.
- **The disclaimer + scope blocks are walls of text.** They're correct and important, but they're the first thing a returning user sees every single session. Returning users don't need the same prominence as first-time users — consider a collapsed "we covered this last time" treatment for repeat sessions.
- **End-of-conversation card abruptly replaces the whole page.** The transcript the user just had — possibly the most useful artifact of the session — disappears. They have to navigate to `/history` and find the conversation to read what was said. The end-card should sit _above_ (or alongside) the now-frozen transcript, not replace it.
- **Mobile is undesigned.** The viewport is fluid but the card stack on a phone is a long scroll with the controls pinned at the top, transcript far below. On mobile the transcript should be the dominant surface and controls should be a sticky bottom bar.
- **No accessibility affordances visible in the current design.** Captions are implicit (the transcript is the caption), but there's no large-text mode, no high-contrast variant, no way to mute the agent's voice while keeping the transcript. A medical-adjacent product needs to take a11y seriously.

### 3. `/history` — past-conversations list

**What it does today:** Header with "Conversation history" title and a "Talk" link. Below: a list of cards, one per conversation, each showing the start timestamp, message count, and a one-line LLM-generated summary (or "No summary yet."). Empty state is a Card titled "No conversations yet".

**Problems:**

- **No filtering, no search, no grouping.** A user with 30 sessions has a flat reverse-chronological list and no way to find "the one where we talked about my wrist".
- **Summaries are buried.** The summary is the most useful thing on the row but it's rendered as muted secondary text below the timestamp.
- **Date grouping is absent.** "Today / Yesterday / This week / Earlier" headers would orient the user instantly — a raw `toLocaleString()` per row makes the user do mental arithmetic.
- **Message count without a duration is only half the picture.** A 30-message 2-minute session feels different from a 30-message 20-minute session.
- **No tier / outcome at a glance.** Did this session end in a self-care plan, a clinician referral, or an emergent routing? That's the most important fact about the conversation and it's not visible on the row.
- **Empty state misses an opportunity.** It says "Conversations you have with the assistant will appear here." but doesn't link to `/` to start one.

### 4. `/history/:id` — single-conversation detail

**What it does today:** Header with "Conversation" title, "Back to history" link, "Talk" link. Below: a Card whose header shows the start timestamp + summary, and whose content is a list of message bubbles — user / assistant / tool — with role badges and timestamps. `find_clinician` tool messages render the same `ClinicianSuggestions` card as the live page. Generic tool messages render as JSON `<pre>` blocks.

**Problems:**

- **Same tool-call noisiness as the live transcript.** JSON `<pre>` is developer chrome on a user-facing transcript.
- **No scrubbing / no quick-jump.** A long conversation is a long scroll; there's no contents pane, no "jump to clinician suggestions", no per-OPQRST-slot anchor.
- **The OPQRST slot snapshot is gone.** During the live session the user could see the structured slots; after the fact, only the unstructured transcript remains. A "summary" panel showing the final state of the slots — what symptoms, severity, duration the agent actually captured — would be the most reusable artifact of the session.
- **No export / share.** A user who wants to take this to a clinician can't easily print or PDF the transcript.
- **No "continue this thread" affordance.** The user can start a new conversation but not resume context from this one. Whether that's possible product-wise is a separate question, but the UI doesn't even acknowledge the option.
- **Summary appears once, in the card description.** It should be a first-class panel above the transcript with the OPQRST snapshot and the outcome tier.

## Design directions to explore

Treat these as starting points — push back on any of them if a better direction emerges:

1. **Pre-talk landing state vs. in-session state.** The home page is doing two jobs: explaining what Sarjy is to a new user, and being a real-time voice console for a returning user. Consider designing these as _visually distinct modes of the same page_ — generous, marketing-feeling pre-connect; calm, focused, transcript-dominant once connected.
2. **Voice-first affordances.** Listening / thinking / speaking states for the agent. A live waveform or a breathing dot. Push-to-talk variant for noisy environments. A visible "I'm picking you up at -38 dB" mic-level meter so users self-diagnose audio issues.
3. **Two-pane desktop, single-column mobile.** On `lg+`, OPQRST sidebar on the right (sticky), transcript + controls on the left. On mobile, transcript fills the screen, controls in a bottom sheet.
4. **Make the OPQRST panel feel alive.** Progress ring or filled-bar showing "3 of 10 slots". Subtle highlight on the slot just updated. The "next likely question" slot pre-selected. Consider whether non-clinical users even understand the labels — "Onset", "Quality", "Radiation" are clinical jargon and probably need a friendlier rename.
5. **End-of-session as a _layered_ state, not a replacement.** Modal or banner over the transcript, not a takeover. Tier-coded: red for emergent, amber for urgent, neutral for routine. With an explicit CTA — "Find urgent care near me" / "Read what we covered" / "Save to PDF".
6. **History as a useful artifact, not just a log.** Search by symptom. Group by week. Show outcome tier as a colored badge. On the detail page, a "Summary" pane (OPQRST snapshot + outcome + clinician suggestions if any) above the raw transcript, with the transcript collapsible.
7. **Accessibility as a first-class lane.** Visible focus states, keyboard shortcuts (space to toggle mic, escape to disconnect), captions toggle (today the transcript _is_ captions but it's not framed that way), high-contrast and large-text variants, reduced-motion respect for any waveform animation.
8. **Trust signals.** A medical-adjacent product needs them. Where does the data go? How long is it kept? Is it a doctor? The disclaimer banner answers some but the user has to read carefully. Consider iconography, a "Privacy" link in the header, a one-screen "How Sarjy works" walkthrough on first sign-in.
9. **Empty states everywhere.** First-time user with no history. No conversations matching a filter. Tool returned zero clinicians. Mic permission denied. All currently underdesigned.

## What to deliver

For each screen (sign-in, home/talk pre-connect, home/talk in-session, end-of-session, history list, history detail) and at least two viewport widths (mobile ~390px and desktop ~1280px):

- A high-fidelity mockup using the shadcn vocabulary.
- A short rationale (3–5 bullets) covering: what user need it serves, what it changed vs. today's UI, and which shadcn primitives it uses.
- Call out any new component you're proposing that isn't in the shadcn library, and justify why it earns its keep.
- A brief design-system addendum: proposed palette extensions (Sarjy currently has only teal `#0d9488` and amber `#fbbf24` as brand-specific; everything else is shadcn slate defaults), typography scale, spacing rhythm, motion principles for the voice-state indicator.

Be opinionated. The current UI is a working tracer-bullet build, not a design — the goal is to give it shape, voice, and a clear emotional register. Sarjy should feel calm, competent, and honest about its limits.
