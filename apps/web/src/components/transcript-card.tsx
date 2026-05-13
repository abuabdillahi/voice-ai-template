import { type ReactNode, useEffect, useRef } from 'react';

import { ClinicianSuggestions } from '@/components/clinician-suggestions';
import { BrookAvatar } from '@/components/brand';
import type { TranscriptEntry } from '@/lib/livekit-transcript';
import { cn } from '@/lib/utils';

/**
 * Normalised transcript-line shape. Three callers feed this component:
 * the live talk page (LiveKit `TranscriptEntry`), the session-end
 * summary (the same), and the history detail route (Postgres
 * `MessageItem`). Each adapter maps its native shape into a
 * :data:`TranscriptItem` so the bubble / chip layout stays in one
 * place — touching the card here changes all three surfaces.
 */
export type TranscriptItem =
  | {
      kind: 'utterance';
      id: string;
      role: 'user' | 'assistant';
      text: string;
      /** Wall-clock ms used to render the bubble timestamp. Optional so
       *  callers without a per-line clock (rare) can still render. */
      timestamp?: number;
    }
  | {
      kind: 'tool-call';
      id: string;
      toolName: string;
      toolArgs?: Record<string, unknown> | null;
      toolResult?: string | null;
      toolError?: boolean;
      timestamp?: number;
    };

interface TranscriptCardProps {
  items: TranscriptItem[];
  /** Whether the agent is currently producing audio. Drives the
   *  "Brook is speaking…" typing bubble independently of mute state. */
  agentSpeaking?: boolean;
  /** Frozen mode hides the live indicator and disables auto-scroll. */
  frozen?: boolean;
  /** Right-side header slot (e.g., timing chip on history detail). */
  headerRight?: ReactNode;
  /** Override the header title (default "Conversation"). */
  title?: string;
  /** Extra classes for the outermost section — used to pin a maxHeight
   *  on the standalone session-end and history surfaces, or to flex-1
   *  inside an already-bounded column on the talk page. */
  className?: string;
}

export function TranscriptCard({
  items,
  agentSpeaking = false,
  frozen = false,
  headerRight,
  title = 'Conversation',
  className,
}: TranscriptCardProps) {
  // Pin the inner scroller to the bottom whenever a new line lands or
  // the typing indicator toggles. Skipped in frozen mode so the user
  // can scroll back through a completed transcript without the view
  // snapping to the end on every render.
  const scrollRef = useRef<HTMLUListElement | null>(null);
  useEffect(() => {
    if (frozen) return;
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [items.length, agentSpeaking, frozen]);

  return (
    <section
      aria-label="Transcript"
      className={cn(
        'flex min-h-0 flex-col overflow-hidden rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))]',
        className,
      )}
    >
      <header className="flex flex-none items-center justify-between border-b border-[hsl(var(--border))] px-5 py-3.5">
        <div className="flex items-center gap-2">
          <h2 className="text-[15px] font-semibold tracking-tight">{title}</h2>
          {frozen ? (
            <span className="rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--muted))] px-2 py-0.5 text-[11px] font-medium text-[hsl(var(--muted-foreground))]">
              Ended
            </span>
          ) : (
            <span className="rounded-full border border-[hsl(var(--primary-soft-border))] bg-[hsl(var(--primary-soft))] px-2 py-0.5 text-[11px] font-medium text-[hsl(var(--primary-soft-fg))]">
              Live
            </span>
          )}
        </div>
        {headerRight}
      </header>
      <ul
        ref={scrollRef}
        className="m-0 flex min-h-0 flex-1 list-none flex-col gap-4 overflow-y-auto p-0 px-5 py-4"
      >
        {items.length === 0 && frozen ? (
          <li className="text-sm text-[hsl(var(--muted-foreground))]">
            No transcript was captured.
          </li>
        ) : null}
        {items.map((item) =>
          item.kind === 'tool-call' ? (
            <ToolCallChip key={item.id} item={item} />
          ) : (
            <UtteranceBubble key={item.id} item={item} />
          ),
        )}
        {!frozen && agentSpeaking ? <TypingLine label="Brook is speaking…" /> : null}
      </ul>
    </section>
  );
}

interface UtteranceProps {
  item: Extract<TranscriptItem, { kind: 'utterance' }>;
}

function UtteranceBubble({ item }: UtteranceProps) {
  const isUser = item.role === 'user';
  return (
    <li
      data-role={item.role}
      className={cn('flex items-start gap-2.5', isUser && 'flex-row-reverse')}
    >
      {isUser ? (
        <div
          aria-hidden
          className="flex h-7 w-7 flex-none items-center justify-center rounded-full bg-[hsl(var(--user-bubble))] text-[11px] font-semibold text-[hsl(var(--user-bubble-fg))]"
        >
          You
        </div>
      ) : (
        <BrookAvatar size={28} />
      )}
      <div
        className={cn(
          'max-w-[78%] rounded-[14px] px-3.5 py-2.5 text-[14.5px] leading-snug',
          isUser
            ? 'rounded-br-[4px] bg-[hsl(var(--user-bubble))] text-[hsl(var(--user-bubble-fg))]'
            : 'rounded-bl-[4px] bg-[hsl(var(--secondary))] text-[hsl(var(--foreground))]',
        )}
      >
        <p className="whitespace-pre-wrap">{item.text}</p>
        {item.timestamp ? (
          <time
            className={cn(
              'mt-1 block font-mono text-[10.5px]',
              isUser
                ? 'text-[hsl(var(--user-bubble-fg)/0.6)]'
                : 'text-[hsl(var(--muted-foreground))]',
            )}
          >
            {formatClockTime(item.timestamp)}
          </time>
        ) : null}
      </div>
    </li>
  );
}

interface ToolCallProps {
  item: Extract<TranscriptItem, { kind: 'tool-call' }>;
}

function ToolCallChip({ item }: ToolCallProps) {
  // The clinician suggestions tool keeps its rich inline card. Every
  // other tool call collapses into a one-line "Updated triage: …"
  // chip; failures are dropped from the user-facing transcript.
  if (item.toolName === 'find_clinician') {
    return (
      <li data-role="tool-call">
        <ClinicianSuggestions result={item.toolResult ?? null} />
      </li>
    );
  }
  if (item.toolError) return null;
  const summary = summariseTool(item);
  if (!summary) return null;
  return (
    <li
      data-role="tool"
      className="flex items-center gap-2 pl-1 text-[12.5px] text-[hsl(var(--muted-foreground))]"
    >
      <span
        aria-hidden
        className="flex h-5 w-5 flex-none items-center justify-center rounded-md bg-[hsl(var(--primary-soft))] text-[hsl(var(--primary-soft-fg))]"
      >
        <svg
          width="12"
          height="12"
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
      <span>Updated triage:</span>
      <span className="font-medium text-[hsl(var(--foreground))]">{summary}</span>
      {item.timestamp ? (
        <time className="ml-auto font-mono text-[11px]">{formatClockTime(item.timestamp)}</time>
      ) : null}
    </li>
  );
}

function TypingLine({ label }: { label: string }) {
  return (
    <li className="flex items-center gap-2.5" data-role="typing">
      <BrookAvatar size={28} />
      <div className="flex items-center gap-1.5 rounded-[14px] rounded-bl-[4px] bg-[hsl(var(--secondary))] px-3.5 py-2.5">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="h-1.5 w-1.5 rounded-full bg-[hsl(var(--primary))]"
            style={{ animation: `limber-thinking 1.2s ease-in-out ${i * 0.15}s infinite` }}
          />
        ))}
        <span className="ml-1.5 text-xs text-[hsl(var(--muted-foreground))]">{label}</span>
      </div>
    </li>
  );
}

function summariseTool(item: Extract<TranscriptItem, { kind: 'tool-call' }>): string | null {
  if (item.toolName === 'record_symptom' && item.toolArgs) {
    const slot = typeof item.toolArgs.slot === 'string' ? item.toolArgs.slot : null;
    const value = typeof item.toolArgs.value === 'string' ? item.toolArgs.value : null;
    if (slot && value) return `${slot} · ${value}`;
    if (slot) return slot;
  }
  return item.toolName;
}

/**
 * Format a millisecond epoch as the design's "2:41 PM" clock pattern.
 * Always 12-hour with no leading zero on the hour, and a single space
 * before AM/PM. Falls back to the raw input if it isn't a valid date.
 */
export function formatClockTime(timestamp: number): string {
  const d = new Date(timestamp);
  if (Number.isNaN(d.getTime())) return '';
  let hours = d.getHours();
  const minutes = String(d.getMinutes()).padStart(2, '0');
  const period = hours >= 12 ? 'PM' : 'AM';
  hours = hours % 12 || 12;
  return `${hours}:${minutes} ${period}`;
}

/**
 * Adapt LiveKit `TranscriptEntry`s (live talk page + session-end
 * stash) into normalised :data:`TranscriptItem`s. Empty utterances
 * are filtered out to match the previous in-session behaviour, and
 * the list is sorted chronologically so the same view renders for
 * both replays of a stashed snapshot and a live, evolving feed.
 */
export function transcriptItemsFromEntries(entries: TranscriptEntry[]): TranscriptItem[] {
  return entries
    .filter((e) => e.role === 'tool-call' || e.text.trim().length > 0)
    .slice()
    .sort((a, b) => a.createdAt - b.createdAt)
    .map((e) =>
      e.role === 'tool-call'
        ? {
            kind: 'tool-call' as const,
            id: e.id,
            toolName: e.text,
            toolArgs: e.args ?? null,
            toolResult: e.result ?? null,
            toolError: e.error ?? false,
            timestamp: e.createdAt,
          }
        : {
            kind: 'utterance' as const,
            id: e.id,
            role: e.role,
            text: e.text,
            timestamp: e.createdAt,
          },
    );
}
