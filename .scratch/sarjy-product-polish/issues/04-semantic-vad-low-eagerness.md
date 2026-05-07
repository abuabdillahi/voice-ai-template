# Issue 04: Semantic VAD with low eagerness on the realtime model

Status: ready-for-agent

## Parent

`.scratch/sarjy-product-polish/PRD.md`

## What to build

Configure the realtime model with semantic turn detection at low eagerness so that coughs, sighs, throat-clears, and keyboard clicks no longer interrupt the agent mid-sentence, while a softly-spoken interruption attempt still yields the turn. The change is a one-line kwarg at the existing `core.realtime.create_realtime_model` factory plus a module-level constant for the eagerness setting so a future tuning pass can flip it to `"medium"` without re-reading the surrounding code.

Pre-implementation check is part of the slice: confirm the installed version of `livekit-agents`'s OpenAI plugin surfaces `turn_detection` as a constructor kwarg by reading the plugin source in `node_modules`/`site-packages`. If the kwarg is supported, lock semantic VAD with `eagerness: "low"`. If the kwarg is not supported on the installed plugin version, fall back to bumped server-VAD thresholds (`threshold=0.7`, `silence_duration_ms=800`, `prefix_padding_ms=300`) and document the fallback decision in a comment at the factory call site so a future maintainer can find it.

End-to-end vertical: factory change → (verify in staging that the agent no longer cuts off on a deliberate cough during the disclaimer) → integration test or smoke check that a session can still be started and the agent still produces audio.

## Acceptance criteria

- [ ] Pre-implementation: confirmed whether the installed `livekit-agents` OpenAI plugin surfaces `turn_detection` as a constructor kwarg, with the finding noted in the issue comments.
- [ ] If supported: `core.realtime.create_realtime_model` passes `turn_detection={"type": "semantic_vad", "eagerness": "low"}` to the OpenAI plugin's `RealtimeModel` constructor.
- [ ] A module-level constant (e.g. `_TURN_DETECTION_EAGERNESS = "low"`) is defined in `core.realtime` so the eagerness setting is reviewable as a one-line change.
- [ ] If not supported: the factory passes `turn_detection={"type": "server_vad", "threshold": 0.7, "silence_duration_ms": 800, "prefix_padding_ms": 300}`, with a comment at the factory call site explaining why the fallback was selected and pointing at this issue.
- [ ] No changes to `agent.session`, the safety screen, the prompt builder, or any frontend file.
- [ ] Existing realtime / agent-session tests pass unchanged.
- [ ] Manual staging check: a deliberate cough during the agent's disclaimer does not cut the agent off; a softly-spoken "hold on" still does.

## Blocked by

None - can start immediately.
