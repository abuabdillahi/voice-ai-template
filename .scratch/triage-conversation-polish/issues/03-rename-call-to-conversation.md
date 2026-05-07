# Issue 03: Rename "call" → "conversation" in the user-facing surface

Status: needs-triage

## What to build

Sarjy is a voice-based educational triage assistant, not a phone service. The user mental model is "I had a conversation with Sarjy", but several user-visible surfaces still call the interaction a "call" — the end-of-conversation card headlines say "This call has ended" / "Call ended", the React component is named `EndOfCallCard`, the file is `end-of-call-card.tsx`, and adjacent doc-comment prose refers to the "end-of-call card" as a UI concept.

Align the user-facing vocabulary with the product's framing: rename the user-visible surface from "call" to "conversation". This is a wide rename — symbol names, file names, test names, and user-visible strings all change so a future contributor reading any of those surfaces sees the new vocabulary and does not silently re-introduce the old one.

The rename is scoped to user-facing surface and the component / file / type names that back it. Technical "call" terminology stays unchanged.

End-to-end behaviour: when Sarjy ends the conversation (via either escalation path), the user sees a card whose title reads "This conversation has ended" and whose accessible name is "Conversation ended". Codebase-wide search for "EndOfConversation" finds the component cleanly; "EndOfCall" returns no results.

## Acceptance criteria

- [ ] React component renamed `EndOfCallCard` → `EndOfConversationCard`.
- [ ] Source file renamed to match the new component name.
- [ ] Test file renamed to match, and all assertions reading "call has ended" / "Call ended" / "Call your local emergency..." for region-name lookups are updated to the conversation vocabulary (the literal phone-call instruction inside the script remains).
- [ ] All importers (Talk page, any other consumers) updated to the new symbol and path.
- [ ] User-visible card copy updated: "This call has ended" → "This conversation has ended"; the generic-fallback "Call ended" → "Conversation ended"; aria-label "Call ended" → "Conversation ended".
- [ ] Doc-comment prose that refers to the "end-of-call card" as a UI concept (in the agent worker's session module, the LiveKit session-end hook module, the Talk page comment naming the post-end UI) is updated to "end-of-conversation card".
- [ ] Technical occurrences of "call" remain untouched: "tool call", "function call", "API call", `tool-call` topic / role string, `call_id`, `call.name`, `call.arguments`, "callback", "callable", "caller", and any code-comment usage that refers to a literal function invocation.
- [ ] The literal phone-call instruction "Call your local emergency number now." (and its sibling "If something feels urgent, call your local…" on the home page) stays unchanged — the word "call" there is the correct verb for "use the telephone".
- [ ] All existing frontend tests continue to pass with updated assertions; no behavioural change is introduced.
- [ ] A repo-wide grep for "EndOfCallCard" / "end-of-call-card" / "end of call card" returns no hits in source, comments, or tests.

## Blocked by

None - can start immediately.
