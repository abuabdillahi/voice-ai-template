# Issue 14: Cost and abuse guardrails for the public hosted instance

Status: draft
Category: enhancement

## Parent

`.scratch/voice-ai-template/PRD.md`

## What to build

Before the template's reference instance is exposed to the public internet, it needs spend guardrails. OpenAI Realtime bills roughly $0.06/min input + $0.24/min output. With today's "anyone with a working email can sign up and start a session" posture, a single motivated abuser looping a script that holds open sessions can spend several hundred dollars overnight. A merely curious visitor who falls asleep with the tab open costs ~$15. Neither is acceptable for a free public demo.

The deploy plan that surfaced this issue assumes:

- Public hosted instance (one we run), reachable on the open internet.
- LiveKit Cloud + OpenAI Realtime, no provider-side spend cap available.
- Supabase Cloud free tier — no headroom for accidental overruns.

This issue covers the decision *and* the implementation. The decision is recorded inline (not as a separate ADR) so this is grabbable end-to-end.

## Posture options considered

- **(i) Open signup, no caps.** Status quo. Rejected — credit-card-loss event the moment the URL gets shared.
- **(ii) Open signup + per-user daily minute quota + global daily kill switch.** Email signup remains anyone-can-do; quotas keep individual abuse and aggregate spend bounded. **Recommended.** Preserves the "accessible by anyone" goal while making bankruptcy impossible.
- **(iii) Invite-only / waitlist.** Maintainer manually approves signups. Safe but breaks the spirit of (A) — visitors can't try the demo without a human in the loop.
- **(iv) Shared password / single-token auth.** A demo URL with a password posted publicly. Functionally close to (ii) without per-user accounting; harder to revoke a single bad actor.

Going with **(ii)** unless the maintainer overrides during triage.

## Acceptance criteria

### Per-user quota

- [ ] New table `usage_daily(user_id uuid, day date, seconds_consumed int, primary key (user_id, day))`. RLS: same `auth.uid() = user_id` predicate as `user_preferences`.
- [ ] `core.usage.record_seconds(user_id, seconds, day=None)` upserts into the table. Day defaults to UTC today.
- [ ] `core.usage.seconds_remaining(user_id, daily_cap_seconds, day=None)` returns the budget left for the day, never negative.
- [ ] Daily cap default: **600 seconds (10 min)**. Configurable via `USAGE_DAILY_CAP_SECONDS` env var.
- [ ] Agent worker calls `seconds_remaining` at session start. If 0, refuses the session with a spoken "you've reached your daily limit, please come back tomorrow" before disconnecting.
- [ ] Agent worker also samples remaining budget every 60s mid-session and politely terminates when it hits zero.
- [ ] Accounting writes happen every 60s (incremental) and once at session end (final).

### Global kill switch

- [ ] New table `usage_global(day date primary key, seconds_consumed int)`. No RLS — only the agent worker writes here, and it uses the user's JWT (so a per-user RLS-by-service-role pattern doesn't apply). Decide: either grant write to `authenticated` with no row filter, or have the agent maintain a server-side service-role connection just for this counter. Pick whichever has the smaller blast radius; document the choice in the PR.
- [ ] `core.usage.global_seconds_today()` reads the row.
- [ ] Global cap default: **12000 seconds (200 min ≈ $60/day worst case)**. Configurable via `USAGE_GLOBAL_CAP_SECONDS`.
- [ ] Agent worker checks the global cap at session start *after* the per-user check. If exceeded, refuses with "the demo has reached today's usage limit, please try again tomorrow."
- [ ] At 80% of the global cap, agent emits a structured log line `event = "usage_warning"` so an alert can be wired up downstream. (Actual paging is out of scope for this issue.)

### Signup hardening

- [ ] Email confirmation **required** in the Supabase project's Auth settings. README's "(Optional) disable Confirm email" note is reframed to "for local dev; production must leave this on."
- [ ] **Cloudflare Turnstile** on the signup form. Free tier, server-side verification in `apps/api` on a new `/auth/signup-verify` endpoint that the frontend hits before calling Supabase signup. Reject the Supabase signup if the token is invalid.
  - Alternative: hCaptcha. Either is acceptable; pick whichever has less integration friction with the existing Supabase JS flow.
- [ ] `.env.example` documents `TURNSTILE_SITE_KEY` and `TURNSTILE_SECRET_KEY` (or hCaptcha equivalents).

### IP rate limiting

- [ ] `slowapi` (or equivalent) on `/livekit/token`: 5 requests per minute per source IP. 429 on excess.
- [ ] Same limit on the signup-verify endpoint to stop captcha-bypass attempts.
- [ ] Document why the limit isn't lower (legitimate users hit reload, tab restore, etc.).

### Frontend UX

- [ ] Talk page surfaces remaining-minutes-today in the header (small badge: "8 min left today"). Read once on page load via a new `GET /usage/remaining` endpoint.
- [ ] When the agent terminates a session due to quota, the frontend renders a friendly "You've used your daily allowance — come back tomorrow" panel rather than a generic disconnect error.
- [ ] When the global cap is hit, the talk page disables the "Start" button before the user joins a room and explains why. (Avoids a wasted LiveKit room creation + token mint.)

### Tests

- [ ] Unit tests for `core.usage` covering: empty-day reads return 0, upserts accumulate, day rollover at UTC midnight, never-negative remaining.
- [ ] Integration test: agent session refuses to start when user is over quota.
- [ ] Integration test: agent session refuses to start when global cap is hit.
- [ ] Integration test: mid-session termination when remaining hits 0.

### Documentation

- [ ] README "Running in production" section (new) documents the cap env vars, the captcha env vars, the rate limit, and explicitly states the maintainer's stance: "this template assumes any public deployment must run with quotas; the defaults are conservative, set higher only after wiring up alerting."
- [ ] One-line note in `.env.example` next to the cap variables explaining the units (seconds, not minutes — easy to fat-finger).

### Verification

- [ ] `UV_CACHE_DIR="$PWD/.uv-cache" pnpm exec turbo run lint typecheck test --force` exits 0.
- [ ] `pnpm exec prettier --check .` exits 0.
- [ ] Manual: sign up two test users, burn through one's quota, confirm the second user is unaffected and the first sees the friendly limit message.
- [ ] Manual: set `USAGE_GLOBAL_CAP_SECONDS=1` temporarily, confirm both new sessions are refused with the global message.

## Blocked by

None — issues 04, 05, 09 are merged. The accounting hooks slot into the existing agent session lifecycle.

## Comments

> *This was generated by AI during planning.*

**2026-05-04 — Issue created.** Surfaced during a /grill-me session about deploying the template as a public hosted instance. The cost/abuse question was deferred from the deploy planning conversation so the rest of the deploy tree (LiveKit Cloud, Fly.io, three-Docker-app shape, Supabase Cloud free tier, Cloudflare Pages → revised to three-Fly-apps) could be resolved end-to-end. Posture (ii) is recommended; awaiting maintainer ratification before promoting to `ready-for-agent`.
