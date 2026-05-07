# Issue 13: Migrate Supabase JWT verification from legacy HS256 secret to JWKS

Status: ready-for-agent
Category: enhancement

## Parent

`.scratch/sarjy/PRD.md`

## What to build

Supabase has moved from a symmetric HS256 scheme (one shared secret signs and verifies every JWT) to an asymmetric scheme: a private key signs, a public key verifies, fetched via the project's JWKS endpoint. The legacy `JWT Secret` is now read-only — Supabase still uses it to verify tokens during the transition, but it can no longer be regenerated except via rotation, and the migration path is one-way.

Our template currently verifies bearer tokens using the legacy HS256 secret in `core.auth.verify_token`. This still works, but it pins the template to the deprecated path. New downstream users will hit confusing UX: the Supabase project dashboard nudges them away from the legacy secret toward JWT Signing Keys, and the API key panel similarly nudges them from `anon`/`service_role` (JWT-based) toward `publishable`/`secret` (opaque). Aligning the template with the new path means anyone cloning the template lands on the recommended Supabase configuration with no friction.

This issue covers two adjacent migrations:

1. **JWT verification** — switch `core.auth.verify_token` to JWKS-based asymmetric verification. The verifier fetches the project's public keys from `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`, caches them, and verifies tokens with `algorithms=["ES256", "RS256"]`.
2. **API keys** — rename `SUPABASE_ANON_KEY` / `VITE_SUPABASE_ANON_KEY` to `SUPABASE_PUBLISHABLE_KEY` / `VITE_SUPABASE_PUBLISHABLE_KEY`. The environment variable is the only thing that changes; the value is the new publishable key from Supabase's API keys panel. We don't use `service_role` anywhere, so no `secret` key migration is needed unless a future admin endpoint requires one.

The `service_role` migration is explicitly **out of scope** for this issue; if a later feature needs admin access to bypass RLS, that's a separate decision (and a separate `SUPABASE_SECRET_KEY` env var).

## Acceptance criteria

### `packages/core/core/auth.py`

- [ ] `verify_token` switches from `jwt.decode(token, secret, algorithms=["HS256"])` to JWKS-based verification.
- [ ] A small `_get_jwks()` helper fetches `{SUPABASE_URL}/auth/v1/.well-known/jwks.json` via `httpx` with a 5-second timeout and caches the result. Cache invalidation strategy: TTL of ~10 minutes, or invalidate-on-kid-mismatch (when a token's `kid` claim doesn't match any cached key, refetch once before failing). Either approach is acceptable; pick whichever is simpler in 30 lines.
- [ ] `verify_token` uses `algorithms=["ES256", "RS256"]` (Supabase issues ES256 by default but accept RS256 too for forward compatibility).
- [ ] The audience claim is verified as `"authenticated"` (the Supabase default).
- [ ] Token expiry is still verified (this is `jwt.decode`'s default behavior; just don't disable it).
- [ ] Errors map to the same shape as today: `verify_token` raises `InvalidTokenError` (or whatever the existing exception type is) with a structured detail. The FastAPI dependency continues to raise `HTTPException(401)` on failure with `WWW-Authenticate: Bearer`.

### `packages/core/core/config.py`

- [ ] `SUPABASE_JWT_SECRET` becomes optional (`str | None = None`) — kept for backward compatibility during the transition window, but no longer required for the app to start.
- [ ] Add an optional `SUPABASE_JWKS_URL: str | None = None`. When unset, derive from `SUPABASE_URL` (the standard path). When set, use the provided URL — this lets self-hosted Supabase deployments at non-standard paths work without changing code.
- [ ] `SUPABASE_ANON_KEY` is renamed to `SUPABASE_PUBLISHABLE_KEY` throughout the Settings model. Same change in the frontend's Vite-exposed name (`VITE_SUPABASE_ANON_KEY` → `VITE_SUPABASE_PUBLISHABLE_KEY`).
- [ ] If breaking the env-var name is too disruptive for downstream forks, keep `SUPABASE_ANON_KEY` as an alias (read both, prefer the new name) and document the deprecation. Acceptable either way; default is to break cleanly.

### `packages/core/tests/unit/test_auth.py`

The tests currently sign synthetic JWTs with the HS256 secret. Two acceptable approaches:

- [ ] **Approach A** — generate an in-test RSA (or EC) keypair, mount a mocked JWKS endpoint via `httpx.MockTransport`, sign test tokens with the private key, serve the public key via the mocked JWKS. ~30 lines of fixture, reusable across other auth tests. **Preferred** because it exercises the real verification path.
- [ ] **Approach B** — keep HS256 working as a test-only fallback, gated on a `_test_secret` constructor argument. Less code but tests now diverge from production.
- [ ] Whichever path is chosen, all existing test cases (valid token, expired token, malformed token, missing claims) continue to pass.

### `apps/api`

- [ ] `apps/api/api/app.py`, `apps/api/tests/conftest.py`: rename `SUPABASE_ANON_KEY` to `SUPABASE_PUBLISHABLE_KEY` in any Settings construction or fixture references.
- [ ] No new routes; auth is wired through `get_current_user` which transitively uses the new `verify_token`. Should be a zero-line change in the route handlers.
- [ ] `/me` and other auth-required tests continue to pass.

### `apps/web`

- [ ] `apps/web/src/lib/supabase.ts` reads `import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY` instead of `VITE_SUPABASE_ANON_KEY`. The Supabase JS client accepts both shapes — only the env var name changes.
- [ ] Vite type definitions (if any) updated.
- [ ] Frontend tests continue to pass.

### Environment

- [ ] `.env.example` updated: `SUPABASE_ANON_KEY` → `SUPABASE_PUBLISHABLE_KEY`, `VITE_SUPABASE_ANON_KEY` → `VITE_SUPABASE_PUBLISHABLE_KEY`. `SUPABASE_JWT_SECRET` removed (or commented out as legacy with a one-line note).
- [ ] `turbo.json`'s `globalPassThroughEnv` array updated to match the new names.

### Documentation

- [ ] README "Auth setup" section updated to reflect the new key names. The instruction to "copy `Project URL`, `anon public` key, and `JWT Secret`" becomes "copy `Project URL` and `publishable` key" (the JWT secret is no longer needed).
- [ ] One-paragraph note that JWT verification now uses Supabase's JWKS endpoint, with a brief mention that this matches the recommended Supabase 2026+ configuration.
- [ ] Migration note for downstream forks that already cloned an older version of the template, explaining what env vars to rename and that the JWT secret can be removed.

### Verification

- [ ] `UV_CACHE_DIR="$PWD/.uv-cache" pnpm exec turbo run lint typecheck test --force` exits 0 across all packages.
- [ ] `pnpm exec prettier --check .` exits 0.
- [ ] On a manual run with the configured Supabase project: signing in still works, `/me` returns the user, the talk page loads, and the issue 12 demo loop (favorite color persists across sessions) still works end-to-end.

## Blocked by

None — issues 04 and 12 are merged. Can start immediately.

## Comments

> *This was generated by AI during triage.*

**2026-05-04 — Issue created.** Prompted by the Supabase dashboard's nudge to migrate from the legacy JWT secret to JWT Signing Keys, plus the related shift from `anon`/`service_role` JWT-based API keys to opaque `publishable`/`secret` keys. The legacy path still works (verification only; can no longer be regenerated), but the template should align with the recommended Supabase configuration so anyone cloning it lands on the supported path. Scoped to verification + publishable key only; the `service_role` → `secret` migration is deferred since the template doesn't currently use service-role access (everything goes through user JWTs and RLS, which is correct).

**2026-05-04 — Promoted to `ready-for-agent`.** Maintainer authorized via "yes draft and triage it." Issue body above is treated as the agent brief; no separate brief authored (same pattern as issues 01–12). Dependencies (issues 04, 12) are merged. Unblocked.

**2026-05-04 — Implemented.** All AC items met:

- New `core/jwks.py` module: `get_jwks(url, ttl=600)` fetches via httpx with 5s timeout and process-global cache; `invalidate_jwks()` drops the cache for forced refresh.
- `core.auth.verify_token` rewritten to ES256/RS256 verification against the JWKS document. On `JWTError` it invalidates the cache, refetches once, and retries — absorbs Supabase key rotations transparently.
- `core.config.Settings`:
  - `supabase_publishable_key` (required) reads `SUPABASE_PUBLISHABLE_KEY` first, falls back to `SUPABASE_ANON_KEY` via `AliasChoices`. `populate_by_name=True` enabled so direct kwarg construction works.
  - `supabase_jwks_url` (optional) overrides the derived JWKS path for self-hosted Supabase deployments.
  - `supabase_jwt_secret` (optional, deprecated) retained so old `.env` files don't fail validation; verifier no longer reads it.
- All `Settings()` construction sites updated (`packages/core/tests/conftest.py`, `apps/api/tests/conftest.py`, `apps/agent/tests/conftest.py`, `apps/agent/tests/integration/test_session_persistence.py`).
- `core.supabase` parameters renamed (`anon_key` → `publishable_key`).
- Frontend: `apps/web/src/lib/supabase.ts` reads `VITE_SUPABASE_PUBLISHABLE_KEY` first, falls back to `VITE_SUPABASE_ANON_KEY`. `vitest.setup.ts` and the boot-time error message updated.
- Tests rewritten with Approach A (preferred): in-test EC P-256 keypair, `httpx.MockTransport`-style monkey-patch on `get_jwks`, real `jwt.decode` path exercised. Added a kid-rotation test that asserts the cache invalidation + refetch works. Added a JWKS-cache test that asserts TTL-window reuse.
- Documentation: `.env.example`, `turbo.json` `globalPassThroughEnv` updated. README "Auth setup" rewritten to drop `SUPABASE_JWT_SECRET` and document the publishable-key path with a note that the legacy `SUPABASE_ANON_KEY` alias still works.

`service_role` → `secret` migration explicitly out of scope (we don't use service-role access anywhere).

Verified: `pnpm exec turbo run lint typecheck test --force` 12/12 across all packages; `pnpm exec prettier --check .` clean.
