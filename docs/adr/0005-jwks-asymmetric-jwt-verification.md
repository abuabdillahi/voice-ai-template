# ADR 0005: JWKS-based asymmetric JWT verification

Status: Accepted (2026-05-04)
Supersedes: —

## Context

Initial implementation (issue 04) used Supabase's legacy HS256 shared secret to verify access tokens: a single `SUPABASE_JWT_SECRET` env var that both Supabase (signer) and our backend (verifier) held. This worked, but Supabase deprecated the legacy path in 2026 in favour of asymmetric **JWT Signing Keys** (ES256 by default, RS256 supported). New projects sign tokens with the new keys; the legacy secret is read-only verification only.

Two practical consequences of staying on the legacy path:

1. **Newly created Supabase projects fail out of the box** — tokens are signed with ES256 keys, our HS256 verify produces 401 on every authed call (we hit this; see `GOTCHAS.md`).
2. **Misaligned with the recommended Supabase configuration** — the dashboard nudges users away from legacy on every visit.

In parallel, Supabase renamed `anon` → `publishable` and `service_role` → `secret` API keys. Same data, new vocabulary.

## Decision

Migrate to **JWKS-based asymmetric verification**.

- `core.auth.verify_token` fetches the project's public keys from `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`, caches them with a TTL (default 600s) plus invalidate-on-`kid`-miss for key rotations. Verifies tokens with `algorithms=["ES256", "RS256"]`.
- `SUPABASE_PUBLISHABLE_KEY` replaces `SUPABASE_ANON_KEY`. Pydantic settings accepts the legacy name as an alias so old `.env` files keep working.
- `SUPABASE_JWT_SECRET` becomes optional and unused (kept in the `Settings` model for backward compat).
- Optional `SUPABASE_JWKS_URL` overrides the derived JWKS endpoint for self-hosted Supabase deployments at non-standard paths.

The agent worker is unaffected — it never verified Supabase JWTs, just forwarded them to PostgREST (which does its own verification).

`service_role` → `secret` migration is **out of scope**: this template doesn't use service-role access anywhere. Adding service-role admin endpoints in a downstream app would require a new `SUPABASE_SECRET_KEY` env var; not handled here.

## Consequences

**Positive**

- Newly created Supabase projects work without manual fallback to a legacy secret.
- Verifier never holds a key that can forge tokens. If the backend is compromised, attackers can't issue valid JWTs.
- Standard JWKS pattern (`/.well-known/jwks.json`) — works with any JWT library; recognisable to anyone who's used Auth0/Clerk/Cognito.
- Key rotation is automatic. Supabase rotates → we hit `kid` miss → invalidate cache → refetch → next call succeeds. No manual step.

**Negative**

- One HTTP fetch on first request after process boot or cache expiry. Mitigated by the 10-minute cache.
- Verifier depends on the Supabase JWKS endpoint being reachable. In an air-gapped self-host, set `SUPABASE_JWKS_URL` to the local equivalent.
- Test fixtures slightly heavier — we generate an in-test EC P-256 keypair and monkey-patch `get_jwks` rather than sharing an HS256 secret. ~30 lines of fixture, reusable.

## Alternatives considered

- **Stay on HS256 + legacy secret.** Rejected. Newly created Supabase projects don't issue HS256-compatible tokens, breaking new clones at minute zero.
- **Run both schemes as a transition.** Rejected. Algorithm-confusion risk (HS256 fallback when ES256 is expected). Cleaner to migrate cleanly and keep the legacy `SUPABASE_JWT_SECRET` env var as a no-op for backward `.env` compatibility.

## Pointers

- `packages/core/core/jwks.py` — fetch + TTL cache.
- `packages/core/core/auth.py` — verifier with kid-miss retry.
- `packages/core/core/config.py` — `SUPABASE_PUBLISHABLE_KEY` with `SUPABASE_ANON_KEY` alias; optional `SUPABASE_JWKS_URL`.
- `.scratch/sarjy/issues/13-jwks-jwt-verification.md` — implementation history.
