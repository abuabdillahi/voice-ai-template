import { useEffect, useState } from 'react';
import { type Room } from 'livekit-client';

/**
 * The data-channel topic the agent uses to signal session-end. Mirrors
 * the `SESSION_END_TOPIC` constant in `agent.session` on the Python
 * side. Distinct from `lk.tool-calls` and `lk.triage-state` so the end-
 * of-call card does not have to filter a multi-purpose stream.
 */
const SESSION_END_TOPIC = 'lk.session-end';

/**
 * Why the session ended, and (for `escalation`) which tier the safety
 * screen tripped on. The `reason` field is open for future expansion
 * (e.g. `"out_of_scope"`) but `escalation` is the only value emitted
 * by the agent worker today.
 */
export type SessionEndSignal = {
  reason: string;
  tier?: string;
};

/**
 * Subscribes to the `lk.session-end` topic and returns the latest
 * payload, or `null` if no event has arrived. Mirrors the existing
 * `useLivekitTriageState` and `useLivekitTranscript` patterns.
 *
 * Malformed JSON payloads are dropped — the agent always emits a
 * single JSON object on this topic, so a parse failure indicates a
 * transient transport corruption rather than a wire-contract change.
 */
export function useSessionEndSignal(room: Room | null): SessionEndSignal | null {
  const [signal, setSignal] = useState<SessionEndSignal | null>(null);

  useEffect(() => {
    if (!room) {
      setSignal(null);
      return;
    }

    const handle = async (reader: {
      info: { topic?: string };
      readAll: () => Promise<string>;
    }): Promise<void> => {
      if (reader.info.topic !== SESSION_END_TOPIC) return;
      const raw = await reader.readAll();
      let payload: unknown = null;
      try {
        payload = JSON.parse(raw);
      } catch {
        return;
      }
      if (
        !payload ||
        typeof payload !== 'object' ||
        typeof (payload as { reason?: unknown }).reason !== 'string'
      ) {
        return;
      }
      const next = payload as { reason: string; tier?: unknown };
      setSignal({
        reason: next.reason,
        tier: typeof next.tier === 'string' ? next.tier : undefined,
      });
    };

    type StreamReader = {
      info: { id?: string; attributes?: Record<string, string>; topic?: string };
      readAll: () => Promise<string>;
    };
    type StreamHandler = (
      reader: StreamReader,
      participantInfo: { identity: string },
    ) => Promise<void>;
    const r = room as unknown as {
      registerTextStreamHandler?: (topic: string, handler: StreamHandler) => void;
      unregisterTextStreamHandler?: (topic: string) => void;
    };
    r.registerTextStreamHandler?.(SESSION_END_TOPIC, handle as unknown as StreamHandler);

    // Deliberately *no* `RoomEvent.Disconnected` listener here. The
    // session-end signal exists precisely to inform the UI that the
    // call is ending — the disconnect that follows (server-side room
    // delete plus our own 500ms-drain disconnect) is the natural
    // completion of that flow, not a reason to forget what happened.
    // Prior implementation reset the signal on Disconnected and made
    // the EndOfCallCard flash for ~500ms before the regular Talk page
    // came back, which defeats the whole feature.

    return () => {
      r.unregisterTextStreamHandler?.(SESSION_END_TOPIC);
    };
  }, [room]);

  return signal;
}
