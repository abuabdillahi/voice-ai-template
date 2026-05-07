# Issue 01: Sarjy speaks first when the conversation starts

Status: needs-triage

## What to build

The realtime model currently waits for the user to speak before producing any audio, so the first thing the user hears after joining is silence — even though the system prompt instructs the model to open every conversation with a scripted self-introduction (first-time disclaimer, returning-user refresher, or prior-condition fork).

Make Sarjy proactively produce its scripted opener as soon as the agent session is set up. The opener variant must continue to be selected by the existing system-prompt branching (first-time vs. returning user vs. returning user with a prior condition) — no opener-selection logic should be duplicated on the code side.

End-to-end behaviour: a user joins the room → Sarjy speaks the appropriate opener within the natural startup window → the user can then respond or barge in normally.

## Acceptance criteria

- [ ] After the agent session starts, the realtime model produces an assistant turn without requiring user input first.
- [ ] The opener variant is driven entirely by the system prompt's existing branching rules — no second source of truth for the greeting copy is introduced in the agent code.
- [ ] First-time users hear the literal "Hi, I'm Sarjy." self-introduction plus the educational-tool disclaimer.
- [ ] Returning users hear the short refresher ("Hi, Sarjy here. Quick reminder I'm still an educational tool, not a doctor.") instead of the full disclaimer.
- [ ] Returning users with a prior identified condition hear the refresher followed by the prior-condition fork question.
- [ ] The opener turn is persisted to the conversation transcript like any other assistant turn.
- [ ] If the user starts speaking immediately, the realtime model's barge-in behaviour applies normally — the opener is not allowed to block the user.
- [ ] Integration test asserts an assistant `conversation_item_added` event fires before any user input is processed.

## Blocked by

None - can start immediately.
