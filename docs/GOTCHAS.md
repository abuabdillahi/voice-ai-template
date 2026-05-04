# Gotchas

Bugs that surfaced during the first end-to-end demo of this template, with
the symptom and the fix. Aggregated so the next agent debugging the same
issue can find the answer in 30 seconds instead of an hour.

Each entry: **symptom (verbatim error)** → **cause** → **fix (commit ref)**.

---

## Voice loop

### Agent registers but never receives a job

**Symptom:** Agent log shows `registered worker` then idle. No `received job request` after a participant joins.

**Cause:** livekit-agents 1.x deprecated implicit/automatic dispatch. Workers without a stable `agent_name` and tokens without an explicit `RoomConfiguration.agents` entry never get dispatched.

**Fix:** `WorkerOptions(agent_name="voice-ai-assistant")` plus `AccessToken.with_room_config(RoomConfiguration(agents=[RoomAgentDispatch(agent_name=AGENT_NAME)]))`. The constant `AGENT_NAME` lives in `core.livekit` and is mirrored in `apps/agent/agent/session.py`. (Commit `cc932b0`.)

### Agent crashes on dispatch with `badly formed hexadecimal UUID string`

**Symptom:**

```
ValueError: badly formed hexadecimal UUID string
  File ".../session.py", line ~115, in _resolve_user_from_participant
    return User(id=UUID(identity), email=name)
```

**Cause:** `ctx.token_claims()` returns the **agent's own** join claims (identity is auto-generated like `agent-AJ_…`), not the user's. UUID parse fails. Even when it does parse, the agent's metadata is empty — the Supabase token rides on the _user's_ token.

**Fix:** `await ctx.wait_for_participant()` to get the connecting user, then read identity + metadata from the participant. (Commit `cc19c9a`.)

### Reconnect after disconnect produces a session with no agent

**Symptom:** Disconnect → Connect cycle works at the LiveKit level (browser shows "connected") but the agent never joins. Browser sees its own participant; transcript stays empty.

**Cause:** LiveKit dispatches agents on **room creation**, not on every participant join. Our `/livekit/token` route used a stable room name (`f"user-{userId}"`), so the second connect rejoined the existing room and no new dispatch fired.

**Fix:** Append a `uuid4` nonce to the default room name: `f"user-{userId}-{nonce}"`. Each token request gets a fresh LiveKit room → fresh dispatch. (Commit `7ea9914`.)

### `does not have permission to update own metadata`

**Symptom:** Frontend logs the error next to the mic button when calling `localParticipant.setAttributes(...)` to push the Supabase token.

**Cause:** LiveKit `VideoGrants.can_update_own_metadata` defaults to `false`.

**Fix:** Set `can_update_own_metadata=True` on the grants when minting the token in `core.livekit.issue_token`. (Commit `852735e`.)

### Assistant transcript appears but no audio plays

**Symptom:** User can talk to the agent, sees agent reply text in transcript, but hears nothing.

**Cause:** LiveKit subscribes remote audio tracks automatically but doesn't auto-play them — the app must attach each track to an `<audio>` element.

**Fix:** Listen to `RoomEvent.TrackSubscribed`, call `track.attach()` for audio tracks, append the resulting element to `document.body`. Counterpart `TrackUnsubscribed` cleans up. (Commit `ff79500`.)

### Each user utterance shows up twice in transcript

**Symptom:** Identical user lines duplicated; assistant lines are correct.

**Cause:** The realtime model emits two text streams per user turn (server VAD + realtime echo) under different stream IDs. The id-based upsert in `useLivekitTranscript` treats them as separate entries.

**Fix:** Secondary dedup by `(role, text)` within a 5-second window. Tool-call entries are exempt (their IDs are unique per dispatch). (Commit `ff79500`.)

### `participant.on('attributes_changed', ...)` fails with `'RemoteParticipant' object has no attribute 'on'`

**Symptom:** `agent.supabase_token.refresh_wire_failed` warning at session start.

**Cause:** livekit-rtc's Python `RemoteParticipant` doesn't expose `on()`. Participant events fire on the **Room**, with handler signature `(changed_attrs, participant)`.

**Fix:** Subscribe via `room.on("participant_attributes_changed", handler)`. (Commit `5ee7c63`.)

### `JWT expired` (PGRST303) after ~1 hour of session

**Symptom:** `agent.conversation.append_failed` log line with `error="{'message': 'JWT expired', 'code': 'PGRST303', ...}"`. Tool dispatch + persistence stop working.

**Cause:** Supabase access token has a 1h TTL. The agent captured the token once at session start (from LiveKit metadata) and never refreshed.

**Fix:** Frontend pushes refreshed token via `localParticipant.setAttributes({supabase_access_token: ...})` on Supabase's `TOKEN_REFRESHED` event. Agent listens for `participant_attributes_changed`, mutates `_SessionDeps.supabase_access_token` in place. Wire functions read from `deps` at event time, not from a captured local. (Commits `1e2acc1`, `5ee7c63`, `852735e`.)

### Tools fire but say "I don't have your account credentials handy"

**Symptom:** `set_preference` dispatches successfully but agent's spoken reply is the no-credentials degrade message; nothing persists.

**Cause:** `_SessionDeps` only carried `user` + `log`. `_make_livekit_tool` built `DomainToolContext` without forwarding the Supabase token, so every tool ran with `ToolContext.supabase_access_token = None`.

**Fix:** Add `supabase_access_token` field to `_SessionDeps`, populate it from the resolved token, forward it into `DomainToolContext` at dispatch time. (Commit `8e94b01`.)

---

## Memory

### `Memory.add() got an unexpected keyword argument 'filters'`

**Symptom:** `remember` tool errors with the above on every call.

**Cause:** mem0 ≥2.0's API change — `filters` kwarg was added to `search`/`get_all` but **not** `add`. We initially passed `filters` to all three.

**Fix:** Drop `filters` from the `add` call site. Keep `user_id` (still accepted by `add`). (Commit `8278cc2`.)

### `Top-level entity parameters frozenset({'user_id'}) are not supported in get_all()`

**Symptom:** `recall`/`list_recent` errors with the above.

**Cause:** Same mem0 ≥2.0 API change — per-entity scoping moved from `user_id=...` to `filters={"user_id": ...}` for `search`/`get_all`.

**Fix:** Pass `filters={"user_id": str(user.id)}` to `search` and `get_all`. (Commit `4cfe116`.)

### `LLM extraction failed: 'max_tokens' is not supported with this model. Use 'max_completion_tokens' instead.`

**Symptom:** `remember` tool reports success but no rows land in `mem0_memories`. The LLM call mem0 makes for fact extraction silently fails, so nothing gets stored.

**Cause:** mem0's default LLM call uses the legacy `max_tokens` parameter, which gpt-5 / o-series models reject. If the user's OpenAI key routes the default model to one of those, extraction fails.

**Fix:** Pin mem0's `llm` block to `gpt-4o-mini` (cheap, fast, accepts `max_tokens`). Same for `embedder` to keep the embedding dims (1536) matching the migration. (Commit `1ebcfb4`.)

### `ImportError: Neither 'psycopg' nor 'psycopg2' library is available`

**Symptom:** `/memories/recent` returns 500 on first call.

**Cause:** `psycopg[binary,pool]` was added under `[dependency-groups] dev` for tests. mem0's pgvector backend imports `psycopg` at runtime, but `uv sync` skips dev groups by default in production.

**Fix:** Move `psycopg[binary,pool]` to runtime `dependencies`. (Commit `d3fdf62`.)

### `psycopg.errors.DuplicatePreparedStatement: prepared statement "_pg3_0" already exists`

**Symptom:** First call to `/memories/recent` after a restart succeeds; subsequent ones may flake or surface this error.

**Cause:** Supabase's **transaction pooler** (port 6543) reuses backend connections across transactions, breaking psycopg's auto-prepared statements.

**Fix:** Use the **session pooler** (port 5432). Documented in `.env.example`. (Commit `3bf0a30`.)

### Cross-session preference recall asks `recall` instead of `get_preference`

**Symptom:** "What's my favorite color?" causes the agent to call `recall("favorite color")` and miss, instead of `get_preference("favorite_color")`.

**Cause:** Two failure modes. (a) Preferences weren't preloaded into the system prompt, so the model had to choose a tool. (b) The prompt described both memory paths in equal-weight prose; the model picked `recall` because "user's life context" matched its description.

**Fix:** (a) Load every stored preference at session start and inline them in the prompt as a "Known facts about the user" block. The model verbalises directly without a tool call. (b) Strengthened the system prompt to make `set_preference`/`get_preference` the canonical path for any single-valued named fact and explicitly forbid `recall` for those. (Commits `81646df`, `58669fe`.)

---

## Auth

### Browser shows blank page; console error `Missing Supabase env vars: set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY`

**Symptom:** Vite boots, browser loads, JS bombs at supabase client init.

**Cause:** Vite reads `.env` from the **package root** (`apps/web/`) by default. Our root `.env` is at the monorepo root and isn't seen.

**Fix:** Set `envDir: resolve(__dirname, '../..')` in `apps/web/vite.config.ts`. The frontend now reads `VITE_*` vars from the same root `.env` the api and agent consume. (Commit `ea2bb50`.)

### 401 on every authed call (`/preferences`, `/memories/recent`) right after sign-up

**Symptom:** Sign-in succeeds, browser has a Supabase session, but every protected endpoint returns 401.

**Cause:** The Supabase project was created post-2026 — Supabase migrated to JWT Signing Keys (asymmetric ES256). Our `core.auth.verify_token` was still using the legacy HS256 shared-secret path, so signature verification failed on every token.

**Fix:** Issue 13 — JWKS-based asymmetric verification. `core.auth` fetches the project's public keys from `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`, caches them, refetches on `kid` miss. The legacy `SUPABASE_JWT_SECRET` env var is now optional; `SUPABASE_PUBLISHABLE_KEY` replaces `SUPABASE_ANON_KEY` (alias preserved for backward compat). (Commit `2a84d63`.)

---

## Setup pitfalls (not bugs, but easy to miss)

### Sign-up appears to work but you can never log in

**Cause:** Supabase Auth → Providers → Email has "Confirm email" enabled and there's no SMTP server.

**Fix:** Disable email confirmation in the Supabase dashboard. Documented in the README "Auth setup" section.

### `MEM0_POSTGRES_URL` empty → `failed to resolve host 'None'`

**Cause:** Missing env var. Mem0 needs a direct Postgres connection (not the REST URL).

**Fix:** Set `MEM0_POSTGRES_URL` to Supabase's **Session pooler** URL (Project Settings → Database → Connection string → Session pooler, port `5432`). The direct `db.<ref>.supabase.co` host is IPv6-only and unreachable from Docker Desktop on macOS.

### Docker rebuild needed after a Python dep change

A code-only change → `docker compose restart`. A change to `pyproject.toml` (added a dep, moved one between groups) → `docker compose build api agent` first.

---

## Tests / CI

### Integration tests fail with `FileNotFoundError` on a migration SQL file

**Symptom:**

```
FileNotFoundError: [Errno 2] No such file or directory:
  '<repo>/packages/supabase/migrations/0001_user_preferences.sql'
```

…and similar for `0000_init.sql`, `0002_conversations.sql`, `0003_mem0_memories.sql`.

**Cause:** The three RLS integration tests under `packages/core/tests/integration/` anchored the migrations directory with `Path(__file__).resolve().parents[3]`. From `packages/core/tests/integration/<file>.py` that resolves to `packages/`, so the tests probe `packages/supabase/migrations/...`. The migrations live at the **repo root**, `./supabase/migrations/`, so the correct index is `parents[4]`. CI did not catch this because there was no pytest job — the unit and integration suites were never run automatically. The combination of the two failures meant the integration suite was effectively dark from the day issue 09 landed.

**Fix:** `parents[3]` → `parents[4]` in `test_preferences_rls.py`, `test_conversations_rls.py`, and `test_memory_with_mem0.py` (two locations). Same change added a `tests` job to `.github/workflows/ci.yml` running `uv run pytest` so the same drift on a future tree-shuffle fails loudly within minutes instead of silently for months.

### Integration tests fail with `testcontainers-ryuk-... is already in use`

**Symptom:**

```
docker.errors.APIError: 409 Client Error ... Conflict
  ("Conflict. The container name "/testcontainers-ryuk-<uuid>" is already in use ...")
```

**Cause:** The integration suite has three module-scoped Postgres fixtures (one per RLS test module). The testcontainers-python reaper ("Ryuk") is meant to be a process singleton, but in practice it races itself across module setups and a second instantiation collides with the first. The reaper exists for crash-recovery cleanup of orphaned containers — irrelevant for a tidy `with PostgresContainer(...) as pg` block that already stops the container on a graceful exit.

**Fix:** `packages/core/tests/conftest.py` sets `TESTCONTAINERS_RYUK_DISABLED=true` via `os.environ.setdefault` at import time, before any test module imports `testcontainers`. Idempotent (a developer can still flip it back on with an explicit env var).

### `type "vector" does not exist` in the mem0 integration test

**Symptom:**

```
psycopg.errors.UndefinedObject: type "vector" does not exist
LINE 1: ...m0_memories (id, vector, payload) values ($1, $2::vector, $3...
```

Or, after qualifying the cast: `psycopg.errors.InsufficientPrivilege: permission denied for schema extensions`.

**Cause:** The migration installs pgvector under the `extensions` schema (`create extension ... with schema "extensions"`). Production Supabase configures the runtime roles' `search_path` to include `extensions` and grants `USAGE` on the schema. The plain Postgres testcontainer does neither, so an unqualified `%s::vector` cast can't resolve the type, and even a qualified `%s::extensions.vector` is blocked by schema permissions.

**Fix in `test_memory_with_mem0.py`:**

1. Qualify the cast in `_insert_memory` as `%s::extensions.vector` so it doesn't depend on `search_path`. (Setting `SET LOCAL search_path` per-session looked like the right fix but didn't take effect under the test's `SET LOCAL ROLE authenticated` flow — couldn't isolate why; the qualified cast is bulletproof regardless.)
2. `grant usage on schema extensions to authenticated` in the bootstrap so the role can resolve the qualified type.

---

## How to extend this doc

When you fix a non-obvious bug whose symptom won't be self-explanatory from the code:

1. Add an entry in the relevant section above with **verbatim error text** as the symptom (so future grep'ing finds it).
2. One-paragraph **cause** that explains the gap between intention and reality.
3. **Fix** with a commit hash so the diff is recoverable.

Three-line entries beat sprawling debugging notes. Keep it scannable.
