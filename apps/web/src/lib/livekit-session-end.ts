import { useState } from 'react';
import { type Room } from 'livekit-client';

import { useJsonDataChannelTopic } from '@/lib/livekit-data-channel';

/**
 * The data-channel topic the agent uses to signal session-end. Mirrors
 * the `SESSION_END_TOPIC` constant in `agent.session` on the Python
 * side. Distinct from `lk.tool-calls` and `lk.triage-state` so the end-
 * of-conversation card does not have to filter a multi-purpose stream.
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

const validateSignal = (raw: unknown): SessionEndSignal | null => {
  if (!raw || typeof raw !== 'object') return null;
  const reason = (raw as { reason?: unknown }).reason;
  if (typeof reason !== 'string') return null;
  const tier = (raw as { tier?: unknown }).tier;
  return { reason, tier: typeof tier === 'string' ? tier : undefined };
};

/**
 * Subscribes to the `lk.session-end` topic and returns the latest
 * payload, or `null` if no event has arrived. Mirrors the existing
 * `useLivekitTriageState` and `useLivekitTranscript` patterns.
 *
 * Deliberately *no* `RoomEvent.Disconnected` reset. The session-end
 * signal exists precisely to inform the UI that the conversation is
 * ending — the disconnect that follows (server-side room delete plus
 * our own 500ms-drain disconnect) is the natural completion of that
 * flow, not a reason to forget what happened. A prior implementation
 * reset on Disconnected and made the EndOfConversationCard flash for
 * ~500ms before the regular Talk page came back, which defeated the
 * whole feature.
 */
export function useSessionEndSignal(room: Room | null): SessionEndSignal | null {
  const [signal, setSignal] = useState<SessionEndSignal | null>(null);
  useJsonDataChannelTopic<SessionEndSignal>(room, SESSION_END_TOPIC, validateSignal, setSignal);
  return signal;
}
