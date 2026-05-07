import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { ChevronRight, Mic, MicOff, PhoneCall, PhoneOff } from 'lucide-react';
import { Room, RoomEvent, ConnectionState, Track, type RemoteTrack } from 'livekit-client';

import { apiFetch } from '@/lib/api';
import { supabase } from '@/lib/supabase';
import { useLivekitTranscript, type TranscriptEntry } from '@/lib/livekit-transcript';
import { useLivekitTriageState } from '@/lib/livekit-triage-state';
import { useSessionEndSignal } from '@/lib/livekit-session-end';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { EndOfConversationCard } from '@/components/end-of-conversation-card';
import { TriageSlots } from '@/components/triage-slots';
import { cn } from '@/lib/utils';

interface LivekitTokenResponse {
  token: string;
  url: string;
  room: string;
}

type Status = 'idle' | 'connecting' | 'connected' | 'disconnected';

/**
 * Talk page — the default authenticated landing route.
 *
 * Lifecycle:
 *
 * 1. User clicks "Connect" → `connect` mutation fetches a token from
 *    `/livekit/token` and joins the room.
 * 2. Microphone toggle publishes/unpublishes the local audio track.
 * 3. Transcript hook surfaces three message types: user / assistant
 *    utterances on `lk.transcription`, and tool calls on
 *    `lk.tool-calls` — both emitted by the agent worker.
 * 4. Disconnect tears the room down and clears state.
 */
export function TalkPage() {
  const [room, setRoom] = useState<Room | null>(null);
  const [status, setStatus] = useState<Status>('idle');
  const [micEnabled, setMicEnabled] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const transcript = useLivekitTranscript(room);
  const triageSlots = useLivekitTriageState(room);
  const sessionEndSignal = useSessionEndSignal(room);

  // The agent emits the session-end signal *before* speaking the
  // escalation script — that is by design, so the EndOfConversationCard
  // can render while the audio is still arriving. We deliberately do not
  // call `room.disconnect()` ourselves here: the authoritative
  // teardown is the server-side `room.delete` (issued after the
  // script finishes plus a ~500 ms drain in
  // `_ESCALATION_AUDIO_DRAIN_SECONDS`), which naturally drops the
  // WebRTC connection on the client. A previous version set a 500 ms
  // timer and disconnected here; that race cut the audio track before
  // any script audio had time to play, so the user saw the card but
  // never heard the routing message.

  // Hold a ref to the active room so cleanup on unmount can
  // disconnect even if state has not yet flushed.
  const roomRef = useRef<Room | null>(null);
  useEffect(() => {
    roomRef.current = room;
  }, [room]);

  useEffect(() => {
    return () => {
      void roomRef.current?.disconnect();
    };
  }, []);

  const connectMutation = useMutation({
    mutationFn: async (): Promise<{ room: Room; info: LivekitTokenResponse }> => {
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

      return { room: lkRoom, info };
    },
    onMutate: () => {
      setError(null);
      setStatus('connecting');
    },
    onSuccess: ({ room: lkRoom }) => {
      setRoom(lkRoom);
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

  const isConnecting = status === 'connecting' || connectMutation.isPending;

  // Once a session-end signal has been received, the talk page is no
  // longer a talk page — it's an end-of-conversation screen. Render only
  // the routing card, with no Connect / Disconnect / Mic affordances.
  // Per issue 05's AC: "no Reconnect / Try-again affordance anywhere
  // ... when the end-card is showing." The page chrome (Sign out /
  // History links) lives in the parent route, so the user can still
  // navigate away.
  if (sessionEndSignal) {
    return (
      <div className="flex w-full max-w-3xl flex-col gap-4">
        <EndOfConversationCard signal={sessionEndSignal} />
      </div>
    );
  }

  return (
    <div className="flex w-full max-w-3xl flex-col gap-4">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4">
          <div>
            <CardTitle>Talk to the assistant</CardTitle>
            <CardDescription>Click connect, then unmute to start talking.</CardDescription>
          </div>
          <StatusPill status={status} />
        </CardHeader>
        <CardContent className="flex items-center gap-3">
          {room ? (
            <Button variant="destructive" onClick={() => void disconnect()} aria-label="Disconnect">
              <PhoneOff className="mr-2 h-4 w-4" />
              Disconnect
            </Button>
          ) : (
            <Button
              onClick={() => connectMutation.mutate()}
              disabled={isConnecting}
              aria-label="Connect"
            >
              <PhoneCall className="mr-2 h-4 w-4" />
              {isConnecting ? 'Connecting…' : 'Connect'}
            </Button>
          )}
          <Button
            variant={micEnabled ? 'secondary' : 'outline'}
            onClick={() => void toggleMic()}
            disabled={!room}
            aria-label={micEnabled ? 'Mute microphone' : 'Unmute microphone'}
            aria-pressed={micEnabled}
          >
            {micEnabled ? (
              <>
                <Mic className="mr-2 h-4 w-4" />
                Mic on
              </>
            ) : (
              <>
                <MicOff className="mr-2 h-4 w-4" />
                Mic off
              </>
            )}
          </Button>
          {error && <span className="text-sm text-[hsl(var(--destructive))]">{error}</span>}
        </CardContent>
      </Card>

      <TriageSlots slots={triageSlots} />

      <Card className="flex-1">
        <CardHeader>
          <CardTitle className="text-base">Transcript</CardTitle>
          <CardDescription>Updates live as you and the assistant speak.</CardDescription>
        </CardHeader>
        <CardContent>
          <TranscriptPanel entries={transcript} />
        </CardContent>
      </Card>
    </div>
  );
}

function StatusPill({ status }: { status: Status }) {
  const label =
    status === 'connected'
      ? 'Connected'
      : status === 'connecting'
        ? 'Connecting…'
        : status === 'disconnected'
          ? 'Disconnected'
          : 'Idle';
  return (
    <span
      role="status"
      aria-live="polite"
      className={cn(
        'rounded-full px-3 py-1 text-xs font-medium',
        status === 'connected' && 'bg-green-100 text-green-900',
        status === 'connecting' && 'bg-amber-100 text-amber-900',
        (status === 'disconnected' || status === 'idle') &&
          'bg-[hsl(var(--muted))] text-[hsl(var(--muted-foreground))]',
      )}
    >
      {label}
    </span>
  );
}

function TranscriptPanel({ entries }: { entries: TranscriptEntry[] }) {
  const items = useMemo(
    () =>
      entries
        .filter((e) => e.role === 'tool-call' || e.text.trim().length > 0)
        .slice()
        .sort((a, b) => a.createdAt - b.createdAt),
    [entries],
  );
  if (items.length === 0) {
    return (
      <p className="text-sm text-[hsl(var(--muted-foreground))]">
        No transcript yet. Say something once you are connected and unmuted.
      </p>
    );
  }
  return (
    <ul className="flex flex-col gap-2 text-sm">
      {items.map((entry) =>
        entry.role === 'tool-call' ? (
          <ToolCallEntry key={entry.id} entry={entry} />
        ) : (
          <UtteranceEntry key={entry.id} entry={entry} />
        ),
      )}
    </ul>
  );
}

function UtteranceEntry({ entry }: { entry: TranscriptEntry }) {
  const variant: 'default' | 'secondary' = entry.role === 'user' ? 'default' : 'secondary';
  return (
    <li
      className={cn(
        'rounded-md px-3 py-2',
        entry.role === 'user'
          ? 'bg-[hsl(var(--accent))] text-[hsl(var(--accent-foreground))]'
          : 'bg-[hsl(var(--secondary))] text-[hsl(var(--secondary-foreground))]',
      )}
    >
      <Badge variant={variant} className="mr-2 align-middle text-[10px] uppercase tracking-wide">
        {entry.role}
      </Badge>
      <span>{entry.text}</span>
    </li>
  );
}

function ToolCallEntry({ entry }: { entry: TranscriptEntry }) {
  const [open, setOpen] = useState(false);
  const argsText = entry.args ? JSON.stringify(entry.args, null, 2) : '{}';
  const resultText = entry.result ?? '';
  return (
    <li
      className={cn(
        'rounded-md border px-3 py-2',
        entry.error
          ? 'border-[hsl(var(--destructive))]/40 bg-[hsl(var(--destructive))]/5'
          : 'border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40',
      )}
    >
      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger
          className="flex w-full items-center justify-between gap-2 text-left"
          aria-label={`Toggle details for tool ${entry.text}`}
        >
          <span className="flex items-center gap-2">
            <Badge
              variant={entry.error ? 'destructive' : 'outline'}
              className="text-[10px] uppercase tracking-wide"
            >
              tool
            </Badge>
            <code className="font-mono text-xs">{entry.text}</code>
          </span>
          <ChevronRight
            className={cn('h-4 w-4 transition-transform', open && 'rotate-90')}
            aria-hidden
          />
        </CollapsibleTrigger>
        <CollapsibleContent className="mt-2 flex flex-col gap-2">
          <div>
            <p className="text-[10px] uppercase tracking-wide text-[hsl(var(--muted-foreground))]">
              Arguments
            </p>
            <pre className="mt-1 overflow-x-auto rounded bg-[hsl(var(--background))] p-2 font-mono text-xs">
              {argsText}
            </pre>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wide text-[hsl(var(--muted-foreground))]">
              Result
            </p>
            <pre className="mt-1 overflow-x-auto rounded bg-[hsl(var(--background))] p-2 font-mono text-xs">
              {resultText || '(no result)'}
            </pre>
          </div>
        </CollapsibleContent>
      </Collapsible>
    </li>
  );
}
