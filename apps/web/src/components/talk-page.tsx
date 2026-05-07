import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useNavigate } from '@tanstack/react-router';
import { AlertTriangle, Mic, MicOff, PhoneOff, Shield, ChevronDown } from 'lucide-react';
import {
  Room,
  RoomEvent,
  ConnectionState,
  Track,
  type RemoteTrack,
  type Participant,
} from 'livekit-client';

import { apiFetch } from '@/lib/api';
import { supabase } from '@/lib/supabase';
import { useLivekitTranscript, type TranscriptEntry } from '@/lib/livekit-transcript';
import { TRIAGE_SLOTS, useLivekitTriageState } from '@/lib/livekit-triage-state';
import { useSessionEndSignal, type SessionEndSignal } from '@/lib/livekit-session-end';
import { Button } from '@/components/ui/button';
import { useSmViewport } from '@/lib/use-viewport';
import { TriageSlots } from '@/components/triage-slots';
import { TranscriptCard, transcriptItemsFromEntries } from '@/components/transcript-card';
import { VoiceDot, voiceStateCopy, type VoiceState } from '@/components/voice-dot';
import {
  SessionSummary,
  clearSessionSummary,
  stashSessionSummary,
} from '@/components/session-summary';
import { cn } from '@/lib/utils';

interface LivekitTokenResponse {
  token: string;
  url: string;
  room: string;
}

interface PriorSessionStatusResponse {
  is_returning_user: boolean;
}

type Status = 'idle' | 'connecting' | 'connected' | 'disconnected';

const EXAMPLE_PROMPTS = [
  'My wrist tingles when I type',
  "I've had a tension headache since lunch",
  'My lower back hurts after long meetings',
  'Eye strain by 4pm every day',
];

const HOW_IT_WORKS = [
  {
    n: '01',
    t: 'You talk',
    d: "Describe what hurts. I'll ask follow-up questions like a triage nurse would.",
  },
  {
    n: '02',
    t: 'I listen + map',
    d: 'Your answers fill a structured triage chart you can see live on the right.',
  },
  {
    n: '03',
    t: 'You leave with a plan',
    d: 'Self-care routine, clinic referral, or — rarely — emergency routing.',
  },
];

/**
 * Talk page — the default authenticated landing surface.
 *
 * Three visual modes share one mounted component:
 *
 *   1. **Pre-connect** — a generous, marketing-feeling hero with a
 *      single "Start talking" CTA. Connect + unmute fuse into one
 *      click; the mic permission preflight is the only gate.
 *   2. **In-session** — a transcript-dominant two-pane layout with a
 *      sticky OPQRST rail. A connection bar at the top shows the
 *      VoiceDot (listening / speaking / muted), mic level, and elapsed
 *      time. Tool calls collapse into one-line transcript chips.
 *   3. **End-of-session** — once `lk.session-end` fires, a tier-coded
 *      `<EndOfConversationCard/>` banner sits *above* the frozen
 *      transcript and triage chart. The banner is the routing
 *      surface; no Connect/Disconnect/Mic affordances render and the
 *      session-end signal is latched for the lifetime of the mount,
 *      so the user cannot fall back into the voice loop. (See
 *      `useSessionEndSignal` for why the latch matters.)
 *
 * The agent emits the session-end signal *before* speaking the
 * escalation script, so the EndOfConversationCard can render while the
 * audio is still arriving. We deliberately do not call
 * `room.disconnect()` ourselves here: the authoritative teardown is
 * the server-side `room.delete` (issued after the script finishes plus
 * a ~500 ms drain in `_ESCALATION_AUDIO_DRAIN_SECONDS`), which
 * naturally drops the WebRTC connection on the client. A previous
 * version set a 500 ms timer and disconnected here; that race cut the
 * audio track before any script audio had time to play, so the user
 * saw the card but never heard the routing message.
 */
export function TalkPage() {
  const [room, setRoom] = useState<Room | null>(null);
  const [status, setStatus] = useState<Status>('idle');
  const [micEnabled, setMicEnabled] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [agentSpeaking, setAgentSpeaking] = useState(false);
  // Latches `true` the first time the agent speaks in a session, and
  // resets on disconnect / fresh connect. Used to discriminate the
  // brief connecting → first-greeting window from the regular
  // listening state — we don't want the connection bar to read "I'm
  // listening, take your time" before Sarjy has even said hello,
  // because it tempts users to talk over the opener.
  const [agentHasSpoken, setAgentHasSpoken] = useState(false);
  useEffect(() => {
    if (agentSpeaking) setAgentHasSpoken(true);
  }, [agentSpeaking]);
  const transcript = useLivekitTranscript(room);
  const triageSlots = useLivekitTriageState(room);
  const sessionEndSignal = useSessionEndSignal(room);
  const navigate = useNavigate();

  const roomRef = useRef<Room | null>(null);
  useEffect(() => {
    roomRef.current = room;
  }, [room]);

  // Trailing quiet-window timer for the VoiceDot "speaking" debounce.
  // See the ActiveSpeakersChanged handler below for why this exists.
  const speakingResetTimerRef = useRef<number | null>(null);

  // When an escalation `lk.session-end` arrives we hand off to the
  // dedicated `/session-end` route immediately, but the agent's
  // routing-script audio is still being delivered over the live
  // WebRTC connection — calling `room.disconnect()` on unmount would
  // cut it mid-sentence. We mirror the signal into a ref so the
  // unmount cleanup can read the latest value and skip the disconnect
  // when a session-end is in flight. The server tears the room down
  // naturally once the script finishes (`_ESCALATION_AUDIO_DRAIN_SECONDS`
  // on the agent side); the LiveKit client's TrackUnsubscribed handler
  // detaches the `<audio>` element when that lands.
  const skipDisconnectOnUnmountRef = useRef(false);
  useEffect(() => {
    skipDisconnectOnUnmountRef.current = !!sessionEndSignal;
  }, [sessionEndSignal]);

  useEffect(() => {
    return () => {
      if (!skipDisconnectOnUnmountRef.current) {
        void roomRef.current?.disconnect();
      }
      if (speakingResetTimerRef.current !== null) {
        window.clearTimeout(speakingResetTimerRef.current);
      }
    };
  }, []);

  const connectMutation = useMutation({
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
      // VoiceDot "speaking" derives from LiveKit's server-side VAD via
      // ActiveSpeakersChanged, not from `<audio>` playback events.
      // The audio element is "playing" continuously once attached
      // (silence is still playback), so its events fire constantly and
      // would leave the indicator stuck on "speaking". The active-
      // speakers list, by contrast, is the model the LiveKit room
      // actually uses to decide who has the floor. The agent emits no
      // dedicated voice-state topic yet; this is the closest accurate
      // signal we have without a wire-protocol change.
      //
      // The active-speakers list updates every few hundred ms during
      // speech, dropping the agent during natural inter-sentence
      // pauses. Without smoothing the indicator flickers on/off as the
      // agent talks in chunks. We therefore latch "speaking" to true
      // on any rising edge and only flip it back to false after a
      // trailing quiet window — long enough to bridge a sentence
      // boundary, short enough that the user notices when the turn
      // actually completes. A user-side rising edge collapses the
      // window immediately so interrupts don't leave the indicator
      // stuck on for ~800ms after the agent has yielded.
      lkRoom.on(RoomEvent.ActiveSpeakersChanged, (speakers: Participant[]) => {
        const localId = lkRoom.localParticipant.identity;
        const agentTalking = speakers.some((p) => p.identity !== localId);
        const userTalking = speakers.some((p) => p.identity === localId);
        if (agentTalking) {
          if (speakingResetTimerRef.current !== null) {
            window.clearTimeout(speakingResetTimerRef.current);
            speakingResetTimerRef.current = null;
          }
          setAgentSpeaking(true);
          return;
        }
        if (userTalking) {
          if (speakingResetTimerRef.current !== null) {
            window.clearTimeout(speakingResetTimerRef.current);
            speakingResetTimerRef.current = null;
          }
          setAgentSpeaking(false);
          return;
        }
        if (speakingResetTimerRef.current !== null) return;
        speakingResetTimerRef.current = window.setTimeout(() => {
          speakingResetTimerRef.current = null;
          setAgentSpeaking(false);
        }, 800);
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
      // Drop any stale stash from a prior session so a refresh of
      // `/session-end` after starting a fresh one redirects home
      // rather than resurfacing the old summary.
      clearSessionSummary();
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

  const [endedLocally, setEndedLocally] = useState(false);
  // Snapshot the transcript + triage state at the moment the session
  // ends — either the agent's `lk.session-end` signal arrives, or the
  // user clicks End session. The live `useLivekitTranscript` and
  // `useLivekitTriageState` hooks reset to `[]` / `{}` on
  // `RoomEvent.Disconnected`, which fires shortly after either trigger.
  // Without a snapshot the frozen view would render empty transcript
  // and triage cards as soon as the WebRTC teardown lands — losing the
  // most useful artifact of the session.
  const [snapshot, setSnapshot] = useState<{
    transcript: TranscriptEntry[];
    triageSlots: Record<string, string>;
  } | null>(null);
  const liveRef = useRef<{ transcript: TranscriptEntry[]; triageSlots: Record<string, string> }>({
    transcript: [],
    triageSlots: {},
  });
  useEffect(() => {
    liveRef.current = { transcript, triageSlots };
  }, [transcript, triageSlots]);

  // Reset the "agent has spoken" latch on every fresh connect so the
  // next session starts in the connecting state again, not in the
  // listening state inherited from the previous one.
  useEffect(() => {
    if (status === 'connecting') setAgentHasSpoken(false);
  }, [status]);

  const disconnect = async (): Promise<void> => {
    // Snapshot the live transcript + triage state *before* the
    // WebRTC teardown clears them (the `useLivekitTranscript` and
    // `useLivekitTriageState` hooks reset on Disconnected). Setting
    // `endedLocally` flips the render branch into the same
    // FrozenSessionView the escalation path uses — same summary
    // banner, same frozen transcript, same clinician-suggestions
    // recap if the agent surfaced any. The synthesized signal carries
    // `reason: 'user_ended'` and no tier so the EndOfConversationCard
    // renders neutral copy instead of the routing scripts.
    if (!snapshot) {
      setSnapshot({
        transcript: liveRef.current.transcript,
        triageSlots: liveRef.current.triageSlots,
      });
    }
    setEndedLocally(true);
    await room?.disconnect();
    setRoom(null);
    setMicEnabled(false);
    setAgentSpeaking(false);
    setStatus('disconnected');
  };

  const toggleMic = async (): Promise<void> => {
    if (!room) return;
    const next = !micEnabled;
    await room.localParticipant.setMicrophoneEnabled(next);
    setMicEnabled(next);
  };

  const isConnecting = status === 'connecting' || connectMutation.isPending;

  const voiceState: VoiceState = !room
    ? 'idle'
    : !micEnabled
      ? 'muted'
      : agentSpeaking
        ? 'speaking'
        : agentHasSpoken
          ? 'listening'
          : 'connecting';

  useEffect(() => {
    if (sessionEndSignal && !snapshot) {
      setSnapshot({
        transcript: liveRef.current.transcript,
        triageSlots: liveRef.current.triageSlots,
      });
    }
  }, [sessionEndSignal, snapshot]);

  // Hand off to the dedicated `/session-end` route as soon as a
  // snapshot is ready. Two trigger conditions, two timings:
  //   - Escalation (`sessionEndSignal`): navigate IMMEDIATELY, even
  //     though the agent is still speaking the routing script. The
  //     unmount-cleanup ref above keeps the live Room alive so the
  //     `<audio>` element on `document.body` continues to play.
  //   - User-ended (`endedLocally`): wait for `room === null`. The
  //     End-session click already calls `room.disconnect()` and
  //     awaits it, then sets `room = null`; by the time this effect
  //     runs the WebRTC teardown is complete.
  // Routing through a real URL lets the AppHeader's Sarjy → home link
  // actually leave the summary instead of resetting same-page state.
  const navigatedRef = useRef(false);
  useEffect(() => {
    if (navigatedRef.current) return;
    if (!(sessionEndSignal || endedLocally)) return;
    if (!snapshot) return;
    if (endedLocally && room) return;
    navigatedRef.current = true;
    stashSessionSummary({
      signal: sessionEndSignal ?? { reason: 'user_ended' },
      transcript: snapshot.transcript,
      triageSlots: snapshot.triageSlots,
    });
    void navigate({ to: '/session-end' });
  }, [sessionEndSignal, endedLocally, room, snapshot, navigate]);

  // While the audio script is still draining (escalation) the room is
  // still up — render the summary inline so the user sees the
  // routing copy alongside the audio. For user-ended this branch is a
  // brief flash before the navigate effect above takes over.
  if (sessionEndSignal || endedLocally) {
    const effectiveSignal: SessionEndSignal = sessionEndSignal ?? { reason: 'user_ended' };
    const frozen = snapshot ?? { transcript, triageSlots };
    return (
      <SessionSummary
        signal={effectiveSignal}
        transcript={frozen.transcript}
        triageSlots={frozen.triageSlots}
      />
    );
  }

  if (!room) {
    return (
      <PreConnectView
        isConnecting={isConnecting}
        error={error}
        onStart={() => connectMutation.mutate()}
      />
    );
  }

  return (
    <InSessionView
      voiceState={voiceState}
      agentSpeaking={agentSpeaking}
      micEnabled={micEnabled}
      transcript={transcript}
      triageSlots={triageSlots}
      onToggleMic={toggleMic}
      onDisconnect={disconnect}
    />
  );
}

// ---- pre-connect view ------------------------------------------------------

interface PreConnectViewProps {
  isConnecting: boolean;
  error: string | null;
  onStart: () => void;
}

function PreConnectView({ isConnecting, error, onStart }: PreConnectViewProps) {
  // The mobile artboard pins the CTA to the bottom of the viewport
  // while the desktop one slots it inline next to its description
  // card. Render the variant that matches the current viewport so the
  // page only ever exposes a single Start talking button — both for
  // accessibility tooling (one CTA, no duplicate ARIA names) and for
  // the test harness, which relies on `getByRole` matching exactly one.
  const isSm = useSmViewport();
  // Same predicate the agent uses to choose the long opener vs. the
  // short refresher (see `core.conversations.has_prior_session`). We
  // default to the first-time treatment until the query resolves so a
  // brand-new user never sees the collapsed pill before the audio
  // disclaimer plays.
  const { data: priorStatus } = useQuery({
    queryKey: ['sessions', 'prior-status'],
    queryFn: () => apiFetch<PriorSessionStatusResponse>('/sessions/prior-status'),
    staleTime: 60_000,
  });
  const isReturningUser = priorStatus?.is_returning_user ?? false;
  return (
    <div className="sarjy-hero-bg flex w-full flex-col px-4 pb-[112px] pt-6 sm:px-8 sm:py-12 sm:pb-12 lg:px-10 lg:py-14">
      <div className="mx-auto grid w-full max-w-[1180px] gap-8 lg:grid-cols-[1fr_360px] lg:gap-12">
        <div>
          <span className="sarjy-eyebrow text-[hsl(var(--primary-soft-fg))]">
            Voice triage · office strain
          </span>
          <h1 className="mt-2 mb-3 max-w-[620px] font-serif text-[32px] leading-[1.25] tracking-[-0.015em] sm:mb-4 sm:text-[40px] sm:leading-[1.15] lg:text-[56px]">
            Take your time.
            <br />
            <span className="italic text-[hsl(var(--foreground)/0.78)]">
              I&apos;m here whenever you&apos;re ready.
            </span>
          </h1>
          <p className="mb-7 max-w-[520px] text-[14px] leading-[1.5] text-[hsl(var(--muted-foreground))] sm:mb-9 sm:text-[15px] sm:leading-[1.55] lg:text-[17px]">
            Sarjy is a voice assistant that helps you think through office-related aches — wrist,
            eyes, neck, back, headaches. Talk for a few minutes; I&apos;ll either suggest what to
            try at home, or point you to a clinician.
          </p>

          {isSm ? (
            <div
              className="flex max-w-[540px] flex-col gap-4 rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5 sm:flex-row sm:items-center sm:gap-6 sm:p-6"
              style={{
                boxShadow:
                  '0 1px 0 hsl(var(--border)), 0 16px 40px -20px hsl(var(--primary) / 0.18)',
              }}
            >
              <Button
                onClick={onStart}
                disabled={isConnecting}
                size="lg"
                className="h-14 rounded-[14px] px-6 text-[15px]"
                aria-label="Start talking"
              >
                <Mic className="mr-2 h-5 w-5" />
                {isConnecting ? 'Connecting…' : 'Start talking'}
              </Button>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium text-[hsl(var(--foreground))]">
                  One click. Mic turns on automatically.
                </div>
                <div className="mt-0.5 text-[13px] text-[hsl(var(--muted-foreground))]">
                  Sessions usually run 4–8 minutes.
                </div>
              </div>
            </div>
          ) : null}
          {error ? (
            <div
              role="alert"
              className="mt-4 max-w-[540px] rounded-md border border-[hsl(var(--destructive))]/30 bg-[hsl(var(--destructive))]/5 px-3 py-2 text-sm text-[hsl(var(--destructive))]"
            >
              {error}
            </div>
          ) : null}

          <div className="mt-7 sm:mt-9">
            <div className="sarjy-eyebrow mb-2.5">Try saying something like</div>
            {/* Mobile: vertical italic cards (one per line) per the
                handoff design. Desktop falls back to the wrapping pill
                row that fits more prompts in less space. */}
            <div className="flex flex-col gap-1.5 sm:hidden">
              {EXAMPLE_PROMPTS.slice(0, 2).map((s) => (
                <div
                  key={s}
                  className="rounded-[calc(var(--radius))] border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-3.5 py-2.5 text-[13px] italic text-[hsl(var(--foreground))]"
                >
                  &ldquo;{s}&rdquo;
                </div>
              ))}
            </div>
            <div className="hidden max-w-[620px] flex-wrap gap-2 sm:flex">
              {EXAMPLE_PROMPTS.map((s) => (
                <span
                  key={s}
                  className="rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-3.5 py-2 text-[13.5px] italic text-[hsl(var(--foreground))]"
                >
                  &ldquo;{s}&rdquo;
                </span>
              ))}
            </div>
          </div>

          {/* The "01 You talk · 02 I listen · 03 You leave with a plan"
              process strip is desktop-only — the mobile artboard drops
              it in favor of a tighter, single-task pre-connect surface. */}
          <div className="mt-10 hidden max-w-[720px] gap-4 sm:mt-12 sm:grid sm:grid-cols-3">
            {HOW_IT_WORKS.map((s) => (
              <div key={s.n} className="border-t border-[hsl(var(--border))] pt-3.5">
                <div className="mb-1.5 font-mono text-[11px] text-[hsl(var(--muted-foreground))]">
                  {s.n}
                </div>
                <div className="mb-1 text-[14.5px] font-semibold">{s.t}</div>
                <div className="text-[13px] leading-snug text-[hsl(var(--muted-foreground))]">
                  {s.d}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* The disclaimer card ships on every breakpoint — it's the
            safety surface, and the mobile artboard renders the same
            first-time-vs-returning treatment above the CTA. The
            "I can help with…" scope list is desktop-only; the mobile
            design folds the in-scope conditions into the headline body
            copy and the disclaimer's own one-liner. */}
        <aside aria-label="What this tool can help with" className="flex flex-col gap-4">
          <DisclaimerSafetyCard isReturningUser={isReturningUser} />
          <div className="hidden sm:block">
            <ScopeCard />
          </div>
        </aside>
      </div>

      {/* Mobile sticky bottom CTA. Pinned to the viewport so the
          primary action is always one thumb-reach away even when the
          user has scrolled into the safety + scope cards. Only
          rendered below the `sm` breakpoint so the desktop card above
          is the sole CTA on wider viewports. */}
      {!isSm ? (
        <div className="fixed inset-x-0 bottom-0 z-20 border-t border-[hsl(var(--border))] bg-[hsl(var(--card))] px-4 pb-5 pt-3">
          <Button
            onClick={onStart}
            disabled={isConnecting}
            size="lg"
            className="h-12 w-full rounded-[14px] text-[15px]"
            aria-label="Start talking"
          >
            <Mic className="mr-2 h-5 w-5" />
            {isConnecting ? 'Connecting…' : 'Start talking'}
          </Button>
          <div className="mt-2 text-center text-[11.5px] text-[hsl(var(--muted-foreground))]">
            Mic turns on automatically. Sessions usually run 4–8 minutes.
          </div>
        </div>
      ) : null}
    </div>
  );
}

interface DisclaimerSafetyCardProps {
  isReturningUser: boolean;
}

function DisclaimerSafetyCard({ isReturningUser }: DisclaimerSafetyCardProps) {
  const [open, setOpen] = useState(false);
  if (!isReturningUser) {
    return (
      <section
        role="region"
        aria-label="Educational tool disclaimer"
        className="rounded-md border border-[hsl(var(--amber-soft-border))] bg-[hsl(var(--amber-soft))] p-4"
      >
        <div className="flex gap-2.5">
          <AlertTriangle className="mt-0.5 h-4 w-4 flex-none text-[hsl(var(--amber-icon))]" />
          <div>
            <div className="text-[13.5px] font-semibold text-[hsl(var(--amber-soft-fg-strong))]">
              I&apos;m an educational tool, not a doctor.
            </div>
            <div className="mt-1 text-[13px] leading-relaxed text-[hsl(var(--amber-soft-body))]">
              If you have crushing chest pain, sudden weakness on one side, vision loss, or signs of
              a stroke, call your local emergency number now.
            </div>
          </div>
        </div>
      </section>
    );
  }
  return (
    <section
      role="region"
      aria-label="Educational tool disclaimer"
      className="overflow-hidden rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))]"
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2.5 px-4 py-3 text-left"
      >
        <Shield className="h-4 w-4 flex-none text-[hsl(var(--amber-icon))]" />
        <div className="flex-1 text-[13px] text-[hsl(var(--muted-foreground))]">
          <span className="font-medium text-[hsl(var(--foreground))]">Safety scope.</span>{' '}
          Educational tool, not a doctor.
        </div>
        <ChevronDown
          className={cn(
            'h-4 w-4 flex-none text-[hsl(var(--muted-foreground))] transition-transform',
            open && 'rotate-180',
          )}
        />
      </button>
      {open ? (
        <div className="border-t border-[hsl(var(--border))] bg-[hsl(var(--amber-soft))] px-4 py-3 text-[13px] leading-relaxed text-[hsl(var(--amber-soft-body))]">
          <p className="font-semibold text-[hsl(var(--amber-soft-fg-strong))]">
            This is an educational tool, not a doctor.
          </p>
          <p className="mt-1">
            Sarjy helps you think about office-strain symptoms and what to try first. It is not a
            substitute for professional medical advice. If you have crushing chest pain, sudden
            weakness on one side, vision loss, or signs of a stroke, call your local emergency
            number now.
          </p>
        </div>
      ) : null}
    </section>
  );
}

const IN_SCOPE_LIST = [
  'Carpal tunnel-type wrist pain',
  'Computer vision / eye strain',
  'Tension-type headache',
  'Upper-trap, "text neck" strain',
  'Lumbar strain from sitting',
];

function ScopeCard() {
  return (
    <section
      role="region"
      aria-label="What this tool can help with"
      className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5"
    >
      <div className="sarjy-eyebrow mb-2.5">I can help with</div>
      <ul className="m-0 grid list-none gap-2.5 p-0">
        {IN_SCOPE_LIST.map((s) => (
          <li key={s} className="flex items-center gap-2.5 text-[13.5px]">
            <span className="flex h-4 w-4 flex-none items-center justify-center rounded-full bg-[hsl(var(--primary-soft))] text-[hsl(var(--primary-soft-fg))]">
              <svg
                width="10"
                height="10"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="3"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M20 6 9 17l-5-5" />
              </svg>
            </span>
            {s}
          </li>
        ))}
      </ul>
      <hr className="my-4 border-t border-[hsl(var(--border))]" />
      <div className="sarjy-eyebrow mb-2">I&apos;ll route you away from</div>
      <p className="text-[12.5px] leading-snug text-[hsl(var(--muted-foreground))]">
        Medications · mental health · pregnancy · paediatric · post-surgical care. I&apos;ll point
        you to a better resource.
      </p>
    </section>
  );
}

// ---- in-session view -------------------------------------------------------

interface InSessionViewProps {
  voiceState: VoiceState;
  agentSpeaking: boolean;
  micEnabled: boolean;
  transcript: TranscriptEntry[];
  triageSlots: Record<string, string>;
  onToggleMic: () => void | Promise<void>;
  onDisconnect: () => void | Promise<void>;
}

function InSessionView({
  voiceState,
  agentSpeaking,
  micEnabled,
  transcript,
  triageSlots,
  onToggleMic,
  onDisconnect,
}: InSessionViewProps) {
  // The session column is height-bounded on every breakpoint so the
  // transcript card claims the remaining vertical space and scrolls
  // internally instead of pushing the controls below the fold. On
  // mobile this is what makes the auto-scroll-to-bottom feel right —
  // without an upper bound the page itself grows past the viewport
  // and the user has to manually scroll the whole page each time the
  // agent or user speaks. We use `100dvh` on mobile so the iOS
  // address-bar collapse doesn't strand the controls bar off-screen.
  // The viewport offsets account for the sticky AppHeader (~56px) plus
  // the page padding above; the `max-h` cap on desktop keeps very tall
  // monitors from feeling sparse.
  const items = transcriptItemsFromEntries(transcript);
  return (
    <main className="mx-auto grid w-full max-w-[1280px] grid-cols-1 gap-3 px-4 py-3 sm:gap-5 sm:py-5 lg:grid-cols-[1fr_380px] lg:items-start lg:px-6">
      <section className="flex h-[calc(100dvh-88px)] min-h-0 flex-col gap-3 sm:gap-4 lg:h-[calc(100vh-120px)] lg:max-h-[760px]">
        <ConnectionBar voiceState={voiceState} />
        {/* Mobile: collapsible triage drawer that lives between the
            voice strip and the transcript. Native <details> handles
            the open/close keyboard-accessibly. Hidden on `lg`
            viewports where the right rail takes over. */}
        <MobileTriageDrawer slots={triageSlots} />
        <TranscriptCard items={items} agentSpeaking={agentSpeaking} className="min-h-0 flex-1" />
        <ControlsBar
          micEnabled={micEnabled}
          onToggleMic={onToggleMic}
          onDisconnect={onDisconnect}
        />
      </section>
      <aside className="hidden lg:sticky lg:top-24 lg:block">
        <TriageSlots slots={triageSlots} />
      </aside>
    </main>
  );
}

interface MobileTriageDrawerProps {
  slots: Record<string, string>;
}

function MobileTriageDrawer({ slots }: MobileTriageDrawerProps) {
  const filled = TRIAGE_SLOTS.filter((s) => slots[s.key]?.trim()).length;
  const total = TRIAGE_SLOTS.length;
  const nextSlot = TRIAGE_SLOTS.find((s) => !slots[s.key]?.trim());
  return (
    <details className="group overflow-hidden rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--muted))] lg:hidden">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-2.5">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="flex h-7 w-7 flex-none items-center justify-center rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))] text-[11px] font-bold text-[hsl(var(--primary-soft-fg))]">
            {filled}/{total}
          </span>
          <span className="min-w-0">
            <span className="block text-[13px] font-semibold leading-tight">Triage chart</span>
            <span className="block truncate text-[11px] text-[hsl(var(--muted-foreground))]">
              {nextSlot ? `Asking next: ${nextSlot.label}` : 'All slots gathered'}
            </span>
          </span>
        </div>
        <ChevronDown className="h-4 w-4 flex-none text-[hsl(var(--muted-foreground))] transition-transform group-open:rotate-180" />
      </summary>
      <div className="border-t border-[hsl(var(--border))] bg-[hsl(var(--background))] p-3">
        <TriageSlots slots={slots} />
      </div>
    </details>
  );
}

interface ConnectionBarProps {
  voiceState: VoiceState;
}

function ConnectionBar({ voiceState }: ConnectionBarProps) {
  const copy = voiceStateCopy(voiceState);
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const id = window.setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => window.clearInterval(id);
  }, []);
  const minutes = String(Math.floor(elapsed / 60)).padStart(2, '0');
  const seconds = String(elapsed % 60).padStart(2, '0');

  return (
    <div className="flex items-center gap-4 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-4 py-3">
      <VoiceDot state={voiceState} size={48} />
      <div className="min-w-0 flex-1">
        <div className="text-[16px] font-semibold tracking-tight">{copy.primary}</div>
        <div className="mt-0.5 text-[13px] text-[hsl(var(--muted-foreground))]">{copy.sub}</div>
      </div>
      <span className="hidden font-mono text-xs text-[hsl(var(--muted-foreground))] sm:block">
        {minutes}:{seconds}
      </span>
    </div>
  );
}

interface ControlsBarProps {
  micEnabled: boolean;
  onToggleMic: () => void | Promise<void>;
  onDisconnect: () => void | Promise<void>;
}

function ControlsBar({ micEnabled, onToggleMic, onDisconnect }: ControlsBarProps) {
  return (
    <div className="flex flex-none flex-wrap items-center gap-2 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-3">
      <Button
        onClick={() => void onToggleMic()}
        variant={micEnabled ? 'default' : 'outline'}
        aria-label={micEnabled ? 'Mute microphone' : 'Unmute microphone'}
        aria-pressed={micEnabled}
      >
        {micEnabled ? <Mic className="mr-2 h-4 w-4" /> : <MicOff className="mr-2 h-4 w-4" />}
        {micEnabled ? 'Mute' : 'Unmute'}
      </Button>
      <div className="flex-1" />
      <Button
        variant="ghost"
        size="sm"
        onClick={() => void onDisconnect()}
        aria-label="End session"
      >
        <PhoneOff className="mr-1.5 h-4 w-4" />
        End session
      </Button>
    </div>
  );
}
