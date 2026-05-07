# Issue 01: Rebrand UI to Sarjy and add first-time self-introduction

Status: ready-for-agent

## Parent

`.scratch/sarjy-product-polish/PRD.md`

## What to build

Rename the user-visible product surface from "Ergo Triage" to "Sarjy" and teach the agent to introduce itself as Sarjy in its opening turn. After this slice ships, every user — first-time or returning — lands on a home page titled **Sarjy**, sees Sarjy in the header and disclaimer banner, clicks Connect, and hears the agent open with `"Hi, I'm Sarjy."` immediately followed by the existing full educational-tool disclaimer. Returning-user disclaimer shortening is deliberately deferred to issue 02; this slice keeps every user on the existing full-disclaimer path so the change is purely additive.

The rebrand is confined to the user-visible UI surface plus a single new prompt rule. ADRs, PRDs in `.scratch/`, internal module names (`core.triage`, `triage-slots.tsx`, `TRIAGE_TOOL_NAMES`, `TRIAGE_STATE_TOPIC`, the `triage` tool registry) are preserved deliberately — they are engineering vocabulary, not the product brand.

End-to-end vertical: prompt rule → agent self-introduction → component rename → header text → banner copy → page title → import update → test reference update.

## Acceptance criteria

- [ ] `apps/web/src/components/triage-home.tsx` is renamed to `sarjy-home.tsx`; the exported component is renamed `TriageHome` → `SarjyHome`.
- [ ] The header in the renamed component reads `"Sarjy"`, not `"Ergo Triage"`.
- [ ] The disclaimer banner body reads `"Sarjy helps you think about office-strain symptoms…"` (the rest of the sentence unchanged).
- [ ] `apps/web/index.html` `<title>` reads `"Sarjy"`.
- [ ] `apps/web/src/routes/index.tsx` imports the renamed component from its new path.
- [ ] `apps/web/src/__tests__/HomeRoute.test.tsx` is updated to reference the renamed component / header text and continues to pass.
- [ ] `agent.session._build_static_triage_prompt` (or the equivalent prompt-rule section) contains a verbatim instruction that the agent opens every session with `"Hi, I'm Sarjy."` immediately before the educational-tool disclaimer.
- [ ] The first-time-no-priors prompt-render regression test is updated once, deliberately, to reflect the new opener — and continues to be the byte-for-byte reference for first-time users going forward.
- [ ] No changes to ADRs, `.scratch/` PRDs, `core.triage`, `TRIAGE_TOOL_NAMES`, `TRIAGE_STATE_TOPIC`, `triage-slots.tsx`, the `triage` tool registry, or any Python module name.
- [ ] Web app builds, type-checks, and the existing test suite passes.
- [ ] Agent test suite passes (the static prompt now contains the new rule).

## Blocked by

None - can start immediately.
