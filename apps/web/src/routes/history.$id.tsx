import { Link, createFileRoute, redirect, useParams } from '@tanstack/react-router';
import { useQuery } from '@tanstack/react-query';

import { apiFetch, ApiError } from '@/lib/api';
import { supabase } from '@/lib/supabase';
import { AppHeader } from '@/components/app-header';
import { Badge } from '@/components/ui/badge';
import { TranscriptCard, formatClockTime, type TranscriptItem } from '@/components/transcript-card';

interface ConversationDetailResponse {
  id: string;
  started_at: string;
  ended_at: string | null;
  summary: string | null;
  metadata: Record<string, unknown>;
  messages: MessageItem[];
}

interface MessageItem {
  id: string;
  role: 'user' | 'assistant' | 'tool' | string;
  content: string;
  tool_name: string | null;
  tool_args: Record<string, unknown> | null;
  tool_result: unknown;
  created_at: string;
}

export const Route = createFileRoute('/history/$id')({
  beforeLoad: async () => {
    const { data } = await supabase.auth.getSession();
    if (!data.session) {
      throw redirect({ to: '/sign-in' });
    }
  },
  component: ConversationRoute,
});

function ConversationRoute() {
  const { id } = useParams({ from: '/history/$id' });
  return (
    <div className="flex min-h-screen flex-col">
      <AppHeader active="history" />
      <main className="mx-auto flex w-full max-w-[1180px] flex-1 flex-col gap-4 px-4 py-6 sm:px-6">
        <Link
          to="/history"
          className="inline-flex items-center gap-1.5 text-[13px] text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
        >
          ← All conversations
        </Link>
        <ConversationView id={id} />
      </main>
    </div>
  );
}

/**
 * Detail view for a single past conversation.
 *
 * Layout:
 *  - A hero summary panel that promotes the LLM-generated `summary`
 *    string (the most useful artifact of the session) to first-class
 *    body copy, with timestamp + duration as supporting metadata and
 *    a "Continue" CTA back to /. The OPQRST snapshot would live here
 *    too once the API persists the final triage state on the detail
 *    response — the wire shape exposes a `metadata` bag for that
 *    purpose; populating it is a backend follow-up.
 *  - The full transcript renders below, with `find_clinician` tool
 *    messages keeping their inline rich-card treatment and other
 *    tool messages reduced to one-line "Updated triage: …" chips.
 *    The previous JSON-`<pre>` developer chrome is gone from the
 *    user-facing surface.
 */
export function ConversationView({ id }: { id: string }) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['conversation', id],
    queryFn: () => apiFetch<ConversationDetailResponse>(`/conversations/${id}`),
    staleTime: 30_000,
  });

  if (isLoading) {
    return <p className="text-sm text-[hsl(var(--muted-foreground))]">Loading…</p>;
  }
  if (isError) {
    if (error instanceof ApiError && error.status === 404) {
      return <p className="text-sm text-[hsl(var(--muted-foreground))]">Conversation not found.</p>;
    }
    return (
      <p className="text-sm text-[hsl(var(--destructive))]">
        Couldn&apos;t load the conversation right now.
      </p>
    );
  }
  if (!data) return null;

  const startedAtMs = Date.parse(data.started_at);
  const endedAtMs = data.ended_at ? Date.parse(data.ended_at) : null;
  const headerLabel = formatHistoryHeader(startedAtMs, endedAtMs);
  const items = data.messages.map(messageToTranscriptItem);

  const summaryText = data.summary ?? 'No summary yet — the conversation may still be in progress.';
  return (
    <div className="flex flex-col gap-3 sm:gap-4">
      {/* Mobile: compact outcome card with a tier-style left accent
          and the summary as body copy — matches the handoff's mobile
          history detail. Desktop keeps the larger serif headline so
          the page hero still reads. */}
      <section
        className="rounded-[calc(var(--radius))] border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-3 sm:p-6 sm:[border-left-width:1px]"
        style={{
          borderLeftColor: 'hsl(var(--tier-routine))',
          borderLeftWidth: 3,
        }}
      >
        <div className="mb-2 flex items-center gap-2 sm:mb-3">
          <Badge
            variant="outline"
            className="font-mono text-[10.5px] uppercase tracking-wide sm:text-[11px]"
          >
            {headerLabel}
          </Badge>
        </div>
        {/* Mobile renders the summary as compact body copy (matches
            the handoff's outcome card); desktop promotes it to a
            serif headline. One element with responsive typography so
            the DOM exposes a single source of truth — important for
            the test harness's `getByText` assertions. */}
        <h1 className="text-[13px] font-normal leading-[1.5] text-[hsl(var(--foreground))] sm:font-serif sm:text-[26px] sm:leading-[1.2]">
          {summaryText}
        </h1>
      </section>

      <TranscriptCard
        items={items}
        frozen
        title="Transcript"
        className="min-h-[360px] max-h-[640px] sm:min-h-[420px]"
      />
    </div>
  );
}

/**
 * Adapt a server-side :data:`MessageItem` to the shared
 * :data:`TranscriptItem` shape. The bubble + tool-call rendering
 * lives in :mod:`components/transcript-card`; this function only
 * reshapes the wire payload.
 */
function messageToTranscriptItem(message: MessageItem): TranscriptItem {
  const ts = Date.parse(message.created_at);
  const timestamp = Number.isNaN(ts) ? undefined : ts;
  if (message.role === 'tool') {
    const resultStr =
      typeof message.tool_result === 'string'
        ? message.tool_result
        : message.tool_result === null || message.tool_result === undefined
          ? null
          : JSON.stringify(message.tool_result);
    return {
      kind: 'tool-call',
      id: message.id,
      toolName: message.tool_name ?? 'tool',
      toolArgs: message.tool_args,
      toolResult: resultStr,
      timestamp,
    };
  }
  return {
    kind: 'utterance',
    id: message.id,
    role: message.role === 'user' ? 'user' : 'assistant',
    text: message.content,
    timestamp,
  };
}

/**
 * Header label for the history detail hero: "Today · 2:41 PM · 6m 43s"
 * per the design. The previous implementation used `toLocaleString()`
 * which honored the user's locale, producing right-to-left Arabic
 * text on Arabic systems and other unexpected formats. The design's
 * grammar is intentional, English-only, so we format it ourselves.
 */
function formatHistoryHeader(startedAtMs: number, endedAtMs: number | null): string {
  if (Number.isNaN(startedAtMs)) return '';
  const day = formatRelativeDay(startedAtMs);
  const time = formatClockTime(startedAtMs);
  const parts = [day, time];
  if (endedAtMs && !Number.isNaN(endedAtMs) && endedAtMs > startedAtMs) {
    parts.push(formatDuration(startedAtMs, endedAtMs));
  }
  return parts.join(' · ');
}

function formatRelativeDay(ms: number): string {
  const d = new Date(ms);
  const today = new Date();
  const startOfDay = (date: Date): number =>
    new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
  const days = Math.round((startOfDay(today) - startOfDay(d)) / 86_400_000);
  if (days === 0) return 'Today';
  if (days === 1) return 'Yesterday';
  if (days > 1 && days < 7) {
    return d.toLocaleDateString('en-US', { weekday: 'long' });
  }
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function formatDuration(startedAtMs: number, endedAtMs: number): string {
  const totalSeconds = Math.round((endedAtMs - startedAtMs) / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes === 0) return `${seconds}s`;
  return `${minutes}m ${String(seconds).padStart(2, '0')}s`;
}
