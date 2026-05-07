import { useEffect, useMemo } from 'react';

import { ClinicianSuggestions } from '@/components/clinician-suggestions';
import { EndOfConversationCard } from '@/components/end-of-conversation-card';
import { TriageSlots } from '@/components/triage-slots';
import { TranscriptCard, transcriptItemsFromEntries } from '@/components/transcript-card';
import type { SessionEndSignal } from '@/lib/livekit-session-end';
import type { TranscriptEntry } from '@/lib/livekit-transcript';

interface SessionSummaryProps {
  signal: SessionEndSignal;
  transcript: TranscriptEntry[];
  triageSlots: Record<string, string>;
  /**
   * When `true`, scroll the window to the top on mount. Set on the
   * dedicated `/session-end` route so users land at the banner rather
   * than wherever the in-session transcript had scrolled. The inline
   * rendering during audio drain leaves this off because we don't
   * want to yank the user mid-audio-script.
   */
  scrollToTopOnMount?: boolean;
}

/**
 * Post-session summary surface. Two callers:
 *   - The talk page renders this inline while the agent's escalation
 *     audio is still draining (see `talk-page.tsx`).
 *   - The dedicated `/session-end` route renders it after the WebRTC
 *     teardown completes, restoring the snapshot from sessionStorage.
 *
 * The layout matches the design's end-of-session artboards: a tier-
 * coded banner on top, an optional "Clinicians suggested in this
 * session" recap card, the frozen transcript, and a frozen triage
 * chart in the right rail.
 */
export function SessionSummary({
  signal,
  transcript,
  triageSlots,
  scrollToTopOnMount = false,
}: SessionSummaryProps) {
  useEffect(() => {
    if (!scrollToTopOnMount) return;
    window.scrollTo({ top: 0, behavior: 'auto' });
  }, [scrollToTopOnMount]);

  const clinicianResults = useMemo(
    () =>
      transcript
        .filter((e) => e.role === 'tool-call' && e.text === 'find_clinician')
        .slice()
        .sort((a, b) => a.createdAt - b.createdAt),
    [transcript],
  );

  const items = useMemo(() => transcriptItemsFromEntries(transcript), [transcript]);

  return (
    <main className="mx-auto grid w-full max-w-[1280px] grid-cols-1 gap-3 px-4 py-3 sm:gap-5 sm:py-5 lg:grid-cols-[1fr_380px] lg:items-start lg:px-6">
      <section className="flex flex-col gap-3 sm:gap-4">
        <EndOfConversationCard signal={signal} />
        {clinicianResults.length > 0 ? (
          <section
            aria-label="Clinicians suggested in this session"
            className="flex flex-col gap-3 rounded-[calc(var(--radius))] border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4 sm:p-5"
          >
            <div className="sarjy-eyebrow">Clinicians suggested in this session</div>
            {clinicianResults.map((entry) => (
              <ClinicianSuggestions key={entry.id} result={entry.result ?? null} />
            ))}
          </section>
        ) : null}
        {/* Bound the frozen transcript so a long session doesn't make
            the whole page scroll past the tier banner. The cap mirrors
            the in-session card; on tall monitors the scroller takes
            over once the content overflows. */}
        <TranscriptCard
          items={items}
          frozen
          className="min-h-[360px] sm:min-h-[420px] max-h-[640px]"
        />
      </section>
      {/* The frozen triage chart ships on desktop only. The mobile
          artboard ends with the tier banner over the frozen transcript
          — keeping the page focused on the routing surface and the
          conversation artifact. */}
      <aside className="hidden lg:sticky lg:top-24 lg:block">
        <TriageSlots slots={triageSlots} frozen />
      </aside>
    </main>
  );
}

// ---- session-storage stash --------------------------------------------------

const STASH_KEY = 'sarjy.session-summary.v1';

export interface SessionSummaryStash {
  signal: SessionEndSignal;
  transcript: TranscriptEntry[];
  triageSlots: Record<string, string>;
}

/**
 * Persist a summary payload across the route boundary. The
 * `/session-end` route lives at its own URL so the AppHeader's
 * Sarjy → home navigation actually leaves the summary; that means
 * the summary state has to survive the route change. sessionStorage
 * scopes to the tab and clears when the user closes it, which is the
 * lifetime we want for an in-flight summary.
 */
export function stashSessionSummary(stash: SessionSummaryStash): void {
  try {
    sessionStorage.setItem(STASH_KEY, JSON.stringify(stash));
  } catch {
    // sessionStorage can throw under strict iframe sandboxing or when
    // disabled by user settings. Ignore — the summary will simply be
    // empty in that edge case.
  }
}

export function readSessionSummary(): SessionSummaryStash | null {
  try {
    const raw = sessionStorage.getItem(STASH_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as SessionSummaryStash;
  } catch {
    return null;
  }
}

export function clearSessionSummary(): void {
  try {
    sessionStorage.removeItem(STASH_KEY);
  } catch {
    /* noop */
  }
}
