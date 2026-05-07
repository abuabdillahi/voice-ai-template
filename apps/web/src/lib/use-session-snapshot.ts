import { useEffect, useRef, useState } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { type Room } from 'livekit-client';

import { stashSessionSummary } from '@/components/session-summary';
import type { TranscriptEntry } from '@/lib/livekit-transcript';
import type { SessionEndSignal } from '@/lib/livekit-session-end';

interface Snapshot {
  transcript: TranscriptEntry[];
  triageSlots: Record<string, string>;
}

/**
 * Captures the live transcript + triage state at the moment the session
 * ends, then hands off to the dedicated `/session-end` route.
 *
 * Two trigger conditions, two timings:
 *
 *   - **Escalation** (`signal` arrives): navigate IMMEDIATELY, even
 *     though the agent is still speaking the routing script. The caller
 *     should set `setSkipDisconnectOnUnmount(true)` on the voice session
 *     so the live Room stays alive — the `<audio>` element on
 *     `document.body` continues to play the script.
 *   - **User-ended** (`endLocally()`): wait for `room === null`. The
 *     End-session click already calls `room.disconnect()` and awaits
 *     it, then sets `room = null`; by the time this effect runs the
 *     WebRTC teardown is complete.
 *
 * Routing through a real URL lets the AppHeader's Sarjy → home link
 * actually leave the summary instead of resetting same-page state.
 *
 * The snapshot is necessary because `useLivekitTranscript` and
 * `useLivekitTriageState` reset to `[]` / `{}` on `RoomEvent.Disconnected`,
 * which fires shortly after either trigger. Without it the frozen view
 * would render empty cards as soon as the WebRTC teardown lands.
 */
export function useSessionSnapshot(args: {
  room: Room | null;
  transcript: TranscriptEntry[];
  triageSlots: Record<string, string>;
  signal: SessionEndSignal | null;
  /** When true, the voice session keeps the Room alive on unmount. */
  setSkipDisconnectOnUnmount: (skip: boolean) => void;
}): {
  snapshot: Snapshot | null;
  endedLocally: boolean;
  endLocally: () => void;
} {
  const { room, transcript, triageSlots, signal, setSkipDisconnectOnUnmount } = args;
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [endedLocally, setEndedLocally] = useState(false);
  const navigate = useNavigate();

  // Mirror the live values into a ref so the snapshot can be taken at
  // the instant the signal arrives without re-running the snapshot
  // effect every time the transcript or triageSlots change.
  const liveRef = useRef<Snapshot>({ transcript: [], triageSlots: {} });
  useEffect(() => {
    liveRef.current = { transcript, triageSlots };
  }, [transcript, triageSlots]);

  // Tell the voice session to keep the Room alive on unmount whenever a
  // signal-driven end is in flight. Without this, `room.disconnect()`
  // on unmount would cut the agent's escalation script mid-sentence.
  useEffect(() => {
    setSkipDisconnectOnUnmount(!!signal);
  }, [signal, setSkipDisconnectOnUnmount]);

  useEffect(() => {
    if (signal && !snapshot) {
      setSnapshot({
        transcript: liveRef.current.transcript,
        triageSlots: liveRef.current.triageSlots,
      });
    }
  }, [signal, snapshot]);

  const navigatedRef = useRef(false);
  useEffect(() => {
    if (navigatedRef.current) return;
    if (!(signal || endedLocally)) return;
    if (!snapshot) return;
    if (endedLocally && room) return;
    navigatedRef.current = true;
    stashSessionSummary({
      signal: signal ?? { reason: 'user_ended' },
      transcript: snapshot.transcript,
      triageSlots: snapshot.triageSlots,
    });
    void navigate({ to: '/session-end' });
  }, [signal, endedLocally, room, snapshot, navigate]);

  const endLocally = (): void => {
    if (!snapshot) {
      setSnapshot({
        transcript: liveRef.current.transcript,
        triageSlots: liveRef.current.triageSlots,
      });
    }
    setEndedLocally(true);
  };

  return { snapshot, endedLocally, endLocally };
}
