# Issue 15: `core_conversations.end()` runs before any messages are persisted, suppressing summary on ~all conversations

Status: ready-for-agent
Category: bug

## Parent

`.scratch/voice-ai-template/PRD.md` (issue 09 — conversation persistence tracer)

## What to build

Empirically: of 133 conversations in the database, 132 have `summary = NULL`. Spot-check on `d33ed9b3-e356-4a6e-8488-0e783cdc8b83` confirms the predicted symptom: `ended_at` is set, but it lands earlier than the latest `messages.created_at` for that conversation, and `message_count >= 3` despite `summary` being NULL.

Root cause is in `apps/agent/agent/session.py:698-710`:

```python
try:
    await session.start(agent, room=ctx.room)
finally:
    if conv_id is not None and supabase_token is not None:
        try:
            core_conversations.end(conv_id, supabase_token=supabase_token)
            log.info("agent.conversation.ended", conversation_id=str(conv_id))
        except Exception as exc:  # noqa: BLE001 — best-effort summary
            log.warning("agent.conversation.end_failed", error=str(exc))
    unbind_log_context("session_id", "user_id", "conversation_id")
```

In `livekit-agents` 1.x, `AgentSession.start()` is **not a blocking run-loop** — it is a setup function (see `livekit/agents/voice/agent_session.py:594-857`). It does the I/O wiring, kicks off `_update_activity`, registers a `JobContext.add_shutdown_callback` for real teardown, then returns within seconds. The voice loop continues via background tasks until the job actually shuts down (room close / participant leave).

Therefore the `finally` block fires immediately after setup, **before any `conversation_item_added` event has had a chance to persist a user or assistant turn**. `_list_messages` returns 0 rows, the 3-message threshold is not met, `summary` stays NULL, and the UPDATE only writes `ended_at` (using the still-fresh token, which is why the row is half-written rather than untouched). The 1/133 row that does have a summary is a race-win edge case.

Secondary issue (closed by the same fix): the `end()` call uses the local `supabase_token` variable captured at session start, not `deps.supabase_access_token`. Commit `1e2acc1` (mid-session token refresh) refactored every other persistence call site to read `deps.supabase_access_token` at event time but missed this one. Reading from `deps` inside a shutdown callback gives us the refreshed token automatically.

## Acceptance criteria

### `apps/agent/agent/session.py`

- [ ] `core_conversations.end(...)` is no longer invoked from the `finally` block of `await session.start(...)`.
- [ ] Instead, `end()` is registered as a `JobContext.add_shutdown_callback(...)` so it runs when the job actually shuts down (after the participant disconnects / the room closes).
- [ ] The shutdown callback reads `deps.supabase_access_token` (not the local `supabase_token` captured at session start) so a refreshed token is honoured. This also closes the long-session JWT expiry hole.
- [ ] The shutdown callback retains the existing best-effort posture: it catches exceptions and logs `agent.conversation.end_failed` rather than crashing job teardown.
- [ ] `unbind_log_context("session_id", "user_id", "conversation_id")` continues to run on entrypoint exit (it is independent of the persistence call).

### `apps/agent/tests/integration/test_session_persistence.py`

- [ ] New test that asserts `core_conversations.end` is invoked via a registered `JobContext.add_shutdown_callback` after participant turns have been persisted, not at the moment `session.start` returns. Use a fake `JobContext` whose `add_shutdown_callback` records the callback and lets the test invoke it manually after appending fake messages.
- [ ] New test that asserts the shutdown callback reads `deps.supabase_access_token` (mutate the deps mid-session, then trigger the callback, then assert the call used the new value).

### Regression coverage

- [ ] Existing tests in `apps/agent/tests/integration/test_session_persistence.py` and `packages/core/tests/unit/test_conversations_module.py` continue to pass.

## Blocked by

None — can start immediately.
