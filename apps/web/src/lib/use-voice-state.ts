import { useEffect, useRef, useState } from 'react';
import { type Room, RoomEvent, type Participant } from 'livekit-client';

import type { VoiceState } from '@/components/voice-dot';
import type { VoiceSessionStatus } from '@/lib/use-voice-session';

const QUIET_WINDOW_MS = 800;

/**
 * Derives the user-facing voice state (`idle | connecting | listening |
 * speaking | muted`) from LiveKit's active-speakers list plus mic
 * status.
 *
 * VoiceDot "speaking" derives from server-side VAD via
 * `RoomEvent.ActiveSpeakersChanged`, not from `<audio>` playback events.
 * The audio element is "playing" continuously once attached (silence is
 * still playback), so its events fire constantly and would leave the
 * indicator stuck on "speaking". The active-speakers list, by contrast,
 * is the model the LiveKit room actually uses to decide who has the
 * floor.
 *
 * The list updates every few hundred ms during speech, dropping the
 * agent during natural inter-sentence pauses. Without smoothing the
 * indicator flickers on/off as the agent talks in chunks. We latch
 * "speaking" to true on any rising edge and only flip it back to false
 * after a trailing quiet window — long enough to bridge a sentence
 * boundary, short enough that the user notices when the turn actually
 * completes. A user-side rising edge collapses the window immediately
 * so interrupts don't leave the indicator stuck on for ~800ms after
 * the agent has yielded.
 *
 * Returns `agentSpeaking` separately so callers that drive ambient UI
 * (a breathing dot, a subtle background pulse) can react to the raw
 * signal without re-deriving it from `voiceState === 'speaking'`.
 */
export function useVoiceState(
  room: Room | null,
  micEnabled: boolean,
  status: VoiceSessionStatus,
): { voiceState: VoiceState; agentSpeaking: boolean } {
  const [agentSpeaking, setAgentSpeaking] = useState(false);
  // Latches `true` the first time the agent speaks in a session, and
  // resets on disconnect / fresh connect. Used to discriminate the
  // brief connecting → first-greeting window from the regular
  // listening state — we don't want the connection bar to read "I'm
  // listening, take your time" before Brook has even said hello,
  // because it tempts users to talk over the opener.
  const [agentHasSpoken, setAgentHasSpoken] = useState(false);

  useEffect(() => {
    if (agentSpeaking) setAgentHasSpoken(true);
  }, [agentSpeaking]);

  useEffect(() => {
    if (status === 'connecting') setAgentHasSpoken(false);
  }, [status]);

  const quietTimerRef = useRef<number | null>(null);

  useEffect(() => {
    if (!room) {
      setAgentSpeaking(false);
      if (quietTimerRef.current !== null) {
        window.clearTimeout(quietTimerRef.current);
        quietTimerRef.current = null;
      }
      return;
    }
    const onSpeakers = (speakers: Participant[]): void => {
      const localId = room.localParticipant.identity;
      const agentTalking = speakers.some((p) => p.identity !== localId);
      const userTalking = speakers.some((p) => p.identity === localId);
      if (agentTalking) {
        if (quietTimerRef.current !== null) {
          window.clearTimeout(quietTimerRef.current);
          quietTimerRef.current = null;
        }
        setAgentSpeaking(true);
        return;
      }
      if (userTalking) {
        if (quietTimerRef.current !== null) {
          window.clearTimeout(quietTimerRef.current);
          quietTimerRef.current = null;
        }
        setAgentSpeaking(false);
        return;
      }
      if (quietTimerRef.current !== null) return;
      quietTimerRef.current = window.setTimeout(() => {
        quietTimerRef.current = null;
        setAgentSpeaking(false);
      }, QUIET_WINDOW_MS);
    };
    room.on(RoomEvent.ActiveSpeakersChanged, onSpeakers);
    return () => {
      room.off(RoomEvent.ActiveSpeakersChanged, onSpeakers);
      if (quietTimerRef.current !== null) {
        window.clearTimeout(quietTimerRef.current);
        quietTimerRef.current = null;
      }
    };
  }, [room]);

  const voiceState: VoiceState = !room
    ? 'idle'
    : !micEnabled
      ? 'muted'
      : agentSpeaking
        ? 'speaking'
        : agentHasSpoken
          ? 'listening'
          : 'connecting';

  return { voiceState, agentSpeaking };
}
