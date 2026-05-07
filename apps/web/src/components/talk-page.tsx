import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, Mic, MicOff, PhoneOff, Shield, ChevronDown } from 'lucide-react';

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

  // While the audio script is still draining (escalation) the room is
  // still up — render the summary inline so the user sees the
  // routing copy alongside the audio. For user-ended this branch is a
  // brief flash before the navigate effect inside useSessionSnapshot
  // takes over.
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
