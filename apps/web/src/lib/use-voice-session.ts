import { useEffect, useRef, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Room, RoomEvent, ConnectionState, Track, type RemoteTrack } from 'livekit-client';

import { apiFetch } from '@/lib/api';
import { supabase } from '@/lib/supabase';

export type VoiceSessionStatus = 'idle' | 'connecting' | 'connected' | 'disconnected';

interface LivekitTokenResponse {
  token: string;
  url: string;
  room: string;
}

/**
 * Owns the LiveKit voice-session lifecycle: mic preflight, token fetch,
 * Room construction, connection-state tracking, supabase-token push for
 * RLS-scoped writes, mic toggling, and teardown.
 *
 * Splits *cleanly* from the voice-state derivation (`useVoiceState`) and
 * the session-end snapshot (`useSessionSnapshot`) — the only shared
 * surface is the Room instance returned here, which the other two hooks
 * subscribe to via livekit-client's event API.
 *
 * The unmount cleanup conditionally skips `room.disconnect()` when a
 * session-end signal is in flight: the agent's escalation script is
 * still being delivered over the live WebRTC connection and a client-
 * side disconnect would cut it mid-sentence. The server-side `room.delete`
 * is the authoritative teardown in that path. Callers signal "leave the
 * room alive on unmount" via `setSkipDisconnectOnUnmount(true)` before
 * navigating away.
 */
export function useVoiceSession(): {
  room: Room | null;
  status: VoiceSessionStatus;
  error: string | null;
  micEnabled: boolean;
  isConnecting: boolean;
  connect: () => void;
  disconnect: () => Promise<void>;
  toggleMic: () => Promise<void>;
  setSkipDisconnectOnUnmount: (skip: boolean) => void;
} {
  const [room, setRoom] = useState<Room | null>(null);
  const [status, setStatus] = useState<VoiceSessionStatus>('idle');
  const [micEnabled, setMicEnabled] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const roomRef = useRef<Room | null>(null);
  useEffect(() => {
    roomRef.current = room;
  }, [room]);

  const skipDisconnectOnUnmountRef = useRef(false);
  const setSkipDisconnectOnUnmount = (skip: boolean): void => {
    skipDisconnectOnUnmountRef.current = skip;
  };

  useEffect(() => {
    return () => {
      if (!skipDisconnectOnUnmountRef.current) {
        void roomRef.current?.disconnect();
      }
    };
  }, []);

  const mutation = useMutation({
    mutationFn: async (): Promise<{ room: Room; info: LivekitTokenResponse }> => {
      // One-click start: request the mic permission *before* opening
      // the LiveKit transport so a denied prompt fails fast instead of
      // leaving the user in a "connected but silent" state. The probe
      // track is released immediately — `setMicrophoneEnabled(true)`
      // below is what publishes for real.
      try {
        const probe = await navigator.mediaDevices.getUserMedia({ audio: true });
        probe.getTracks().forEach((t) => t.stop());
      } catch (err) {
        const name = (err as DOMException | null)?.name;
        if (name === 'NotAllowedError' || name === 'PermissionDeniedError') {
          throw new Error('Microphone permission denied. Allow mic access and try again.');
        }
        throw new Error('Could not access your microphone. Check your input device.');
      }

      const info = await apiFetch<LivekitTokenResponse>('/livekit/token', {
        method: 'POST',
        body: {},
      });
      const lkRoom = new Room({ adaptiveStream: true, dynacast: true });
      lkRoom.on(RoomEvent.ConnectionStateChanged, (state: ConnectionState) => {
        if (state === ConnectionState.Connected) setStatus('connected');
        else if (state === ConnectionState.Connecting) setStatus('connecting');
        else if (state === ConnectionState.Reconnecting) setStatus('connecting');
        else if (state === ConnectionState.Disconnected) setStatus('disconnected');
      });
      // Attach every remote audio track to a hidden <audio> element so
      // the browser actually plays the agent's voice. LiveKit subscribes
      // tracks automatically, but it does not auto-play — without this
      // hook the assistant's transcript appears but no sound comes out.
      lkRoom.on(RoomEvent.TrackSubscribed, (track: RemoteTrack) => {
        if (track.kind !== Track.Kind.Audio) return;
        const element = track.attach();
        element.style.display = 'none';
        document.body.appendChild(element);
      });
      lkRoom.on(RoomEvent.TrackUnsubscribed, (track: RemoteTrack) => {
        if (track.kind !== Track.Kind.Audio) return;
        track.detach().forEach((el) => el.remove());
      });
      await lkRoom.connect(info.url, info.token);

      // Push the live Supabase access token as a participant attribute
      // so the agent worker can read it for RLS-scoped writes. The
      // agent reads `supabase_access_token` via `_resolve_supabase_token`
      // and listens for attribute changes; below we re-push on every
      // Supabase TOKEN_REFRESHED event so long sessions stay
      // authenticated past the 1h JWT TTL.
      const pushToken = async (): Promise<void> => {
        const { data } = await supabase.auth.getSession();
        const token = data.session?.access_token;
        if (token) {
          await lkRoom.localParticipant.setAttributes({ supabase_access_token: token });
        }
      };
      await pushToken();
      const { data: authSub } = supabase.auth.onAuthStateChange((event) => {
        if (event === 'TOKEN_REFRESHED' || event === 'SIGNED_IN') {
          void pushToken();
        }
      });
      lkRoom.once(RoomEvent.Disconnected, () => {
        authSub.subscription.unsubscribe();
      });

      // Auto-unmute on connect so the user only has to make one
      // decision ("start talking"). The previous Connect-then-Unmute
      // flow was a friction tax that left users staring at a connected
      // session with a muted mic and no obvious recovery.
      await lkRoom.localParticipant.setMicrophoneEnabled(true);

      return { room: lkRoom, info };
    },
    onMutate: () => {
      setError(null);
      setStatus('connecting');
    },
    onSuccess: ({ room: lkRoom }) => {
      setRoom(lkRoom);
      setMicEnabled(true);
      setStatus('connected');
    },
    onError: (err: unknown) => {
      setError(err instanceof Error ? err.message : 'Failed to connect.');
      setStatus('idle');
    },
  });

  const disconnect = async (): Promise<void> => {
    await room?.disconnect();
    setRoom(null);
    setMicEnabled(false);
    setStatus('disconnected');
  };

  const toggleMic = async (): Promise<void> => {
    if (!room) return;
    const next = !micEnabled;
    await room.localParticipant.setMicrophoneEnabled(next);
    setMicEnabled(next);
  };

  return {
    room,
    status,
    error,
    micEnabled,
    isConnecting: status === 'connecting' || mutation.isPending,
    connect: () => mutation.mutate(),
    disconnect,
    toggleMic,
    setSkipDisconnectOnUnmount,
  };
}
