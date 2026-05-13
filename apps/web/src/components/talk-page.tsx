import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  AlertTriangle,
  ArrowRight,
  Mic,
  MicOff,
  PhoneOff,
  Shield,
  ChevronDown,
} from 'lucide-react';

import { apiFetch } from '@/lib/api';
import { useLivekitTranscript, type TranscriptEntry } from '@/lib/livekit-transcript';
import { TRIAGE_SLOTS, useLivekitTriageState } from '@/lib/livekit-triage-state';
import { useSessionEndSignal, type SessionEndSignal } from '@/lib/livekit-session-end';
import { useVoiceSession } from '@/lib/use-voice-session';
import { useVoiceState } from '@/lib/use-voice-state';
import { useSessionSnapshot } from '@/lib/use-session-snapshot';
import { Button } from '@/components/ui/button';
import { useSmViewport } from '@/lib/use-viewport';
import { TriageSlots } from '@/components/triage-slots';
import { TranscriptCard, transcriptItemsFromEntries } from '@/components/transcript-card';
import { BrookAvatar } from '@/components/brand';
import { VoiceDot, voiceStateCopy, type VoiceState } from '@/components/voice-dot';
import { SessionSummary, clearSessionSummary } from '@/components/session-summary';
import { cn } from '@/lib/utils';

interface PriorSessionStatusResponse {
  is_returning_user: boolean;
}

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
    d: 'Describe what hurts. Brook asks follow-ups like a triage nurse would.',
  },
  {
    n: '02',
    t: 'We map',
    d: 'Answers fill a structured triage chart you can watch live.',
  },
  {
    n: '03',
    t: 'You leave with a plan',
    d: 'Self-care, clinic referral, or — rarely — urgent routing.',
  },
];

const BODY_REGIONS = [
  { label: 'Wrist', sub: 'Carpal tunnel' },
  { label: 'Eye', sub: 'Screen strain' },
  { label: 'Head', sub: 'Tension' },
  { label: 'Neck', sub: 'Text neck' },
  { label: 'Back', sub: 'Lumbar strain' },
];

/**
 * Talk page — the default authenticated landing surface.
 *
 * Three visual modes share one mounted component:
 *
 *   1. **Pre-connect** — limber's marketing hero ("Less stiff by
 *      Friday.") with a Brook "Meet your assistant" card on the right
 *      and a single Start talking CTA. Per the design deviation, the
 *      Brook card uses the same complementary surface as the auth
 *      screens' left column (sand in light, dark-sand in dark) — it
 *      does not lock to dark ink in light mode.
 *   2. **In-session** — a transcript-dominant two-pane layout with a
 *      sticky triage rail. A connection bar at the top shows the
 *      Brook listening indicator, mic level, and elapsed time.
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
 * naturally drops the WebRTC connection on the client.
 */
export function TalkPage() {
  const session = useVoiceSession();
  const transcript = useLivekitTranscript(session.room);
  const triageSlots = useLivekitTriageState(session.room);
  const sessionEndSignal = useSessionEndSignal(session.room);
  const { voiceState, agentSpeaking } = useVoiceState(
    session.room,
    session.micEnabled,
    session.status,
  );
  const { snapshot, endedLocally, endLocally } = useSessionSnapshot({
    room: session.room,
    transcript,
    triageSlots,
    signal: sessionEndSignal,
    setSkipDisconnectOnUnmount: session.setSkipDisconnectOnUnmount,
  });

  const onStart = (): void => {
    // Drop any stale stash from a prior session so a refresh of
    // `/session-end` after starting a fresh one redirects home
    // rather than resurfacing the old summary.
    clearSessionSummary();
    session.connect();
  };

  const onDisconnect = async (): Promise<void> => {
    endLocally();
    await session.disconnect();
  };

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

  if (!session.room) {
    return (
      <PreConnectView isConnecting={session.isConnecting} error={session.error} onStart={onStart} />
    );
  }

  return (
    <InSessionView
      voiceState={voiceState}
      agentSpeaking={agentSpeaking}
      micEnabled={session.micEnabled}
      transcript={transcript}
      triageSlots={triageSlots}
      onToggleMic={session.toggleMic}
      onDisconnect={onDisconnect}
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
    <div className="flex w-full flex-col bg-[hsl(var(--background))] px-4 pb-[120px] pt-6 sm:px-8 sm:py-12 sm:pb-12 lg:px-10 lg:py-14">
      <div className="mx-auto grid w-full max-w-[1200px] gap-10 lg:grid-cols-[1.15fr_1fr] lg:gap-14">
        <div>
          <span className="limber-eyebrow">Voice triage · office strain</span>
          <h1 className="mt-3 mb-4 max-w-[620px] font-sans text-[44px] font-bold leading-[1.0] tracking-[-0.04em] sm:text-[56px] lg:text-[72px] lg:leading-[0.98]">
            Less stiff
            <br />
            <span style={{ color: 'hsl(var(--accent))' }}>by Friday.</span>
          </h1>
          <p className="mb-8 max-w-[520px] text-[15px] leading-[1.55] text-[hsl(var(--muted-foreground))] sm:text-[16px] lg:text-[17px]">
            Five minutes of talking. A plan you can actually follow. For wrist tingling, eye strain,
            headaches, neck pain, and lower-back ache from desk work.
          </p>

          {isSm ? (
            <div
              className="flex max-w-[540px] flex-col items-stretch gap-4 rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5 sm:flex-row sm:items-center sm:gap-5 sm:p-[18px]"
              style={{
                boxShadow:
                  '0 1px 0 hsl(var(--border)), 0 16px 40px -20px hsl(var(--primary) / 0.18)',
              }}
            >
              <Button
                onClick={onStart}
                disabled={isConnecting}
                size="lg"
                className="h-14 rounded-[14px] bg-[hsl(var(--foreground))] px-6 text-[15px] font-semibold text-[hsl(var(--background))] hover:bg-[hsl(var(--foreground))]/90"
                aria-label="Start talking"
              >
                <Mic className="mr-2 h-5 w-5" />
                {isConnecting ? 'Connecting…' : 'Start talking'}
                <ArrowRight className="ml-2 h-4 w-4" style={{ color: 'hsl(var(--accent))' }} />
              </Button>
              <div className="min-w-0 flex-1">
                <div className="text-[13.5px] font-semibold text-[hsl(var(--foreground))]">
                  One tap. Mic turns on.
                </div>
                <div className="mt-0.5 text-[12.5px] text-[hsl(var(--muted-foreground))]">
                  Sessions usually run 4–8 minutes. Pause anytime.
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
            <div className="mb-2.5 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-[hsl(var(--muted-foreground))]">
              Try saying
            </div>
            {/* Mobile: vertical italic cards (one per line). Desktop
                falls back to a wrapping pill row. */}
            <div className="flex flex-col gap-1.5 sm:hidden">
              {EXAMPLE_PROMPTS.slice(0, 2).map((s) => (
                <div
                  key={s}
                  className="rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-3.5 py-2 text-[13px] italic text-[hsl(var(--foreground))]"
                >
                  &ldquo;{s}&rdquo;
                </div>
              ))}
            </div>
            <div className="hidden max-w-[620px] flex-wrap gap-2 sm:flex">
              {EXAMPLE_PROMPTS.map((s) => (
                <span
                  key={s}
                  className="rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-3.5 py-2 text-[13px] italic text-[hsl(var(--foreground))]"
                >
                  &ldquo;{s}&rdquo;
                </span>
              ))}
            </div>
          </div>

          <div className="mt-9 hidden max-w-[720px] gap-4 rounded-2xl bg-[hsl(var(--secondary))] p-6 sm:grid sm:grid-cols-5">
            {BODY_REGIONS.map((x) => (
              <div key={x.label}>
                <div className="text-[13.5px] font-bold text-[hsl(var(--foreground))]">
                  {x.label}
                </div>
                <div className="mt-0.5 text-[11.5px] text-[hsl(var(--muted-foreground))]">
                  {x.sub}
                </div>
              </div>
            ))}
          </div>

          <div className="mt-10 hidden max-w-[720px] gap-4 sm:mt-9 sm:grid sm:grid-cols-3">
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

        {/* The right rail — Brook intro + safety. On every breakpoint
            this is the safety surface. Per the design deviation we
            apply here: the "Meet your assistant" card sits on the
            same complementary surface used by the auth screens' left
            column (`--secondary`, i.e. sand in light, dark-sand in
            dark) rather than locking to dark ink in light mode. */}
        <aside aria-label="Meet Brook" className="flex flex-col gap-4">
          <MeetBrookCard />
          <DisclaimerSafetyCard isReturningUser={isReturningUser} />
        </aside>
      </div>

      {!isSm ? (
        <div className="fixed inset-x-0 bottom-0 z-20 border-t border-[hsl(var(--border))] bg-[hsl(var(--card))] px-4 pb-5 pt-3">
          <Button
            onClick={onStart}
            disabled={isConnecting}
            size="lg"
            className="h-14 w-full rounded-[14px] bg-[hsl(var(--foreground))] text-[15px] font-semibold text-[hsl(var(--background))] hover:bg-[hsl(var(--foreground))]/90"
            aria-label="Start talking"
          >
            <Mic className="mr-2 h-5 w-5" />
            {isConnecting ? 'Connecting…' : 'Start talking'}
            <ArrowRight className="ml-2 h-4 w-4" style={{ color: 'hsl(var(--accent))' }} />
          </Button>
          <div className="mt-2 text-center text-[11.5px] text-[hsl(var(--muted-foreground))]">
            One tap. Mic turns on automatically.
          </div>
        </div>
      ) : null}
    </div>
  );
}

function MeetBrookCard() {
  return (
    <section
      aria-label="Meet your assistant"
      className="relative overflow-hidden rounded-3xl border border-[hsl(var(--border))] bg-[hsl(var(--secondary))] p-7"
    >
      <svg
        aria-hidden
        className="pointer-events-none absolute -right-14 -top-10"
        width="360"
        height="360"
        viewBox="0 0 360 360"
        fill="none"
        style={{ opacity: 0.18 }}
      >
        <circle cx="180" cy="180" r="60" stroke="hsl(var(--primary))" strokeWidth="1" />
        <circle
          cx="180"
          cy="180"
          r="110"
          stroke="hsl(var(--primary))"
          strokeWidth="1"
          opacity="0.7"
        />
        <circle
          cx="180"
          cy="180"
          r="160"
          stroke="hsl(var(--primary))"
          strokeWidth="1"
          opacity="0.45"
        />
      </svg>

      <div className="relative">
        <span className="limber-eyebrow" style={{ color: 'hsl(var(--primary))' }}>
          Meet your assistant
        </span>
        <div className="mt-4 flex items-center gap-4">
          <BrookAvatar size={64} listening />
          <div>
            <div className="text-[26px] font-bold leading-none tracking-[-0.02em] text-[hsl(var(--foreground))]">
              Brook
            </div>
            <div className="mt-1 text-[12px] text-[hsl(var(--muted-foreground))]">
              Voice triage · always teal
            </div>
          </div>
        </div>

        <blockquote
          className="mt-5 border-l-2 pl-4 font-serif text-[20px] italic leading-[1.4] text-[hsl(var(--foreground))]"
          style={{ borderColor: 'hsl(var(--primary))' }}
        >
          &ldquo;I&apos;m calm and quiet. I&apos;ll ask what hurts, then a few follow-ups. I&apos;m
          not a doctor — and I&apos;ll tell you when you need one.&rdquo;
        </blockquote>

        <p className="mt-5 text-[12.5px] leading-[1.55] text-[hsl(var(--muted-foreground))]">
          Brook&apos;s voice is a fixed teal across every limber screen, so you always know
          who&apos;s listening. limber is the chrome — Brook is the persona inside it.
        </p>

        <div className="mt-6">
          <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[hsl(var(--muted-foreground))]">
            Brook says
          </div>
          <ul className="mt-2 flex flex-col gap-1.5">
            {[
              'Hi — I’m Brook. Take your time.',
              'Mm-hm. And how long has that been going on?',
              'Got it. Want to try something for it, or talk to someone in person?',
            ].map((q) => (
              <li
                key={q}
                className="rounded-lg border-l-2 bg-[hsl(var(--card))] px-3 py-2 font-serif text-[13.5px] italic leading-[1.45] text-[hsl(var(--foreground))]"
                style={{ borderColor: 'hsl(var(--primary)/0.4)' }}
              >
                &ldquo;{q}&rdquo;
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
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
        className="rounded-2xl border border-[hsl(var(--amber-soft-border))] bg-[hsl(var(--amber-soft))] p-4"
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
      className="overflow-hidden rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--card))]"
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2.5 px-4 py-3 text-left"
      >
        <Shield className="h-4 w-4 flex-none text-[hsl(var(--amber-icon))]" />
        <div className="flex-1 text-[13px] text-[hsl(var(--muted-foreground))]">
          <span className="font-semibold text-[hsl(var(--foreground))]">Safety scope.</span>{' '}
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
            limber helps you think about office-strain symptoms and what to try first. It is not a
            substitute for professional medical advice. If you have crushing chest pain, sudden
            weakness on one side, vision loss, or signs of a stroke, call your local emergency
            number now.
          </p>
        </div>
      ) : null}
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
  const items = transcriptItemsFromEntries(transcript);
  return (
    <main className="mx-auto grid w-full max-w-[1280px] grid-cols-1 gap-3 px-4 py-3 sm:gap-5 sm:py-5 lg:grid-cols-[1fr_380px] lg:items-start lg:px-6">
      <section className="flex h-[calc(100dvh-88px)] min-h-0 flex-col gap-3 sm:gap-4 lg:h-[calc(100vh-120px)] lg:max-h-[760px]">
        <ConnectionBar voiceState={voiceState} />
        {/* Mobile: collapsible triage drawer between the status row
            and the transcript. Native <details> handles open/close
            keyboard-accessibly. Hidden on `lg` viewports where the
            right rail takes over. */}
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
    <details className="group overflow-hidden rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--secondary))] lg:hidden">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-2.5">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="flex h-7 w-7 flex-none items-center justify-center rounded-md bg-[hsl(var(--primary-soft))] text-[11px] font-bold text-[hsl(var(--primary-soft-fg))]">
            {filled}/{total}
          </span>
          <span className="min-w-0">
            <span className="block text-[13px] font-semibold leading-tight">
              What Brook has gathered
            </span>
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
      <BrookAvatar size={44} listening={voiceState === 'listening'} />
      <div className="min-w-0 flex-1">
        <div className="text-[15px] font-semibold tracking-tight">{copy.primary}</div>
        <div className="mt-0.5 text-[13px] text-[hsl(var(--muted-foreground))]">{copy.sub}</div>
      </div>
      <VoiceDot state={voiceState} size={28} />
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
        className={cn(
          'h-11 rounded-full px-5 text-[14px] font-semibold',
          micEnabled
            ? 'bg-[hsl(var(--primary))] text-white hover:bg-[hsl(var(--primary-strong))]'
            : '',
        )}
        aria-label={micEnabled ? 'Mute microphone' : 'Unmute microphone'}
        aria-pressed={micEnabled}
      >
        {micEnabled ? <Mic className="mr-2 h-4 w-4" /> : <MicOff className="mr-2 h-4 w-4" />}
        {micEnabled ? 'Mute mic' : 'Unmute'}
      </Button>
      <div className="flex-1" />
      <Button
        variant="ghost"
        size="sm"
        onClick={() => void onDisconnect()}
        aria-label="End session"
        className="text-[13px]"
      >
        <PhoneOff className="mr-1.5 h-4 w-4" />
        End session
      </Button>
    </div>
  );
}
