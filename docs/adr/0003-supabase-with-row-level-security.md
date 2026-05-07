# ADR 0003: Supabase as the auth + database stack, RLS for user isolation

Status: Accepted (2026-05-04)
Supersedes: —

## Context

The template needs auth, Postgres, and pgvector. Three reasonable stacks existed in 2026:

- **Clerk + Postgres-of-your-choice** — best-in-class auth UX, BYO DB. Vendor.
- **Supabase** — auth + Postgres + pgvector + Storage + Realtime as one product. Self-hostable.
- **Custom JWT + Postgres** — zero vendors, maximum code to maintain.

The template explicitly requires a Docker-deployable, self-hostable shape (per its PRD).

## Decision

Use **Supabase** for auth, Postgres, and pgvector. Enforce per-user data isolation at the **database layer via Row-Level Security**, not in application code.

Every user-scoped table (`user_preferences`, `conversations`, `messages`, mem0's tables) carries an RLS policy keyed off `auth.uid()`. The application's Postgres calls run as the user's role by passing the Supabase JWT into each request's PostgREST client.

For verification: the template uses Supabase's JWT Signing Keys (asymmetric ES256), not the legacy HS256 shared secret — see ADR 0005.

## Consequences

**Positive**

- Self-hostable end-to-end (Supabase + Postgres in containers), honoring the Docker-deploy requirement fully.
- Bundled pgvector — the memory layer's storage is provisioned by the auth choice; no second database.
- RLS at the DB means a forgotten `WHERE user_id = ?` in app code can't leak. The verification policy lives where the data lives.
- `supabase db push` is the canonical migration story; the same migrations run locally and in production.
- One-line config to switch between Supabase Cloud (dev) and self-hosted Supabase (prod).

**Negative**

- Authentication UI is rougher than Clerk's hosted forms (we ship a custom shadcn sign-in form — ~50 lines).
- Weaker B2B / SSO / org features than Clerk. Acceptable for a template; downstream apps needing enterprise auth swap the seam (`core.auth.verify_token`).
- The Supabase JWT TTL (1h) requires a mid-session refresh path in long-running voice loops (handled via LiveKit participant attributes — see `GOTCHAS.md`).

## Alternatives considered

- **Clerk + Neon/RDS Postgres.** Rejected. Clerk's hosted UI is excellent, but Clerk auth always lives in Clerk's cloud — the template can never be fully self-contained via `docker compose up`. Also no integrated pgvector / RLS-meets-auth story.
- **Custom JWT + Postgres.** Rejected. All of password reset, email delivery, session rotation, JWKS, key rotation become our problem. Wrong default for a "best practices" template.
- **Hybrid Clerk + Supabase Postgres.** Rejected. Two vendors, two SDKs on the frontend, RLS-meets-auth integration fragmented. Worst of both options.

## Pointers

- `packages/core/core/auth.py` — JWT verification (post-ADR-0005).
- `packages/core/core/supabase.py` — per-request token-scoped client builder.
- `supabase/migrations/*.sql` — every user-scoped table carries RLS.
- `.scratch/sarjy/PRD.md` "Identity, database, and memory" section.
