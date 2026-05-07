import { useMemo, useState } from 'react';
import { Link, createFileRoute, redirect } from '@tanstack/react-router';
import { useQuery } from '@tanstack/react-query';
import { ChevronRight, Clock, Mic, Search } from 'lucide-react';

import { apiFetch } from '@/lib/api';
import { supabase } from '@/lib/supabase';
import { AppHeader } from '@/components/app-header';
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

interface ConversationsListResponse {
  conversations: ConversationSummaryItem[];
}

interface ConversationSummaryItem {
  id: string;
  started_at: string;
  ended_at: string | null;
  summary: string | null;
  message_count: number;
}

export const Route = createFileRoute('/history/')({
  beforeLoad: async () => {
    const { data } = await supabase.auth.getSession();
    if (!data.session) {
      throw redirect({ to: '/sign-in' });
    }
  },
  component: HistoryIndexRoute,
});

function HistoryIndexRoute() {
  return (
    <div className="flex min-h-screen flex-col">
      <AppHeader active="history" />
      <main className="mx-auto flex w-full max-w-[880px] flex-1 flex-col gap-6 px-4 py-6 sm:px-6 sm:py-8">
        <HistoryList />
      </main>
    </div>
  );
}

/**
 * Past-conversations list view.
 *
 * Layout per the redesign brief:
 *  - Page hero with session count, "New conversation" CTA on the
 *    right.
 *  - Search input (filters across summary text on the client today;
 *    server-side full-text search is a backend follow-up).
 *  - Rows grouped by Today / This week / Earlier so a user with N
 *    sessions can orient instantly. Each row leads with the LLM
 *    summary (the most useful field on the row), backed by the start
 *    timestamp, computed duration, and message count as secondary
 *    metadata. Outcome-tier coloring is deferred until the API
 *    returns an `outcome_tier` field on the summary.
 *  - Empty state links back to the talk page so a user who just
 *    signed up has a first move available.
 */
export function HistoryList() {
  const [query, setQuery] = useState('');
  const { data, isLoading, isError } = useQuery({
    queryKey: ['conversations'],
    queryFn: () => apiFetch<ConversationsListResponse>('/conversations'),
    staleTime: 10_000,
  });

  const filteredGroups = useMemo(() => {
    if (!data) return [] as Group[];
    const items = data.conversations.filter((it) => {
      if (!query.trim()) return true;
      const needle = query.trim().toLowerCase();
      return (it.summary ?? '').toLowerCase().includes(needle);
    });
    return groupByDate(items);
  }, [data, query]);

  const totalCount = data?.conversations.length ?? 0;
  const lastStarted = data?.conversations[0]?.started_at;

  return (
    <>
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="font-serif text-[28px] leading-[1.15] sm:text-[34px] sm:leading-[1.2]">
            Your conversations
          </h1>
          <p className="mt-1.5 text-sm text-[hsl(var(--muted-foreground))]">
            {totalCount === 0
              ? 'No sessions yet.'
              : totalCount === 1
                ? `1 session · last on ${formatShortDate(lastStarted!)}`
                : `${totalCount} sessions · last on ${formatShortDate(lastStarted!)}`}
          </p>
        </div>
        <Button asChild size="default" className="self-start sm:self-auto">
          <Link to="/">
            <Mic className="mr-1.5 h-4 w-4" /> New conversation
          </Link>
        </Button>
      </header>

      <div className="relative">
        <Search
          className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[hsl(var(--muted-foreground))]"
          aria-hidden
        />
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by symptom or what was said…"
          aria-label="Search conversations"
          className="pl-10"
        />
      </div>

      {isLoading ? (
        <p className="text-sm text-[hsl(var(--muted-foreground))]">Loading…</p>
      ) : isError ? (
        <p className="text-sm text-[hsl(var(--destructive))]">
          Couldn&apos;t load your conversations right now.
        </p>
      ) : (data?.conversations.length ?? 0) === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">No conversations yet</CardTitle>
            <CardDescription>
              Conversations you have with the assistant will appear here.{' '}
              <Link
                to="/"
                className="text-[hsl(var(--primary))] underline-offset-2 hover:underline"
              >
                Start your first one →
              </Link>
            </CardDescription>
          </CardHeader>
        </Card>
      ) : filteredGroups.length === 0 ? (
        <p className="text-sm text-[hsl(var(--muted-foreground))]">
          No conversations match &ldquo;{query}&rdquo;.
        </p>
      ) : (
        filteredGroups.map((g) => (
          <section key={g.group} className="flex flex-col gap-2">
            <div className="sarjy-eyebrow">{g.group}</div>
            <ul className="flex flex-col gap-2">
              {g.items.map((item) => (
                <li key={item.id}>
                  <HistoryRow item={item} group={g.group} />
                </li>
              ))}
            </ul>
          </section>
        ))
      )}
    </>
  );
}

function HistoryRow({ item, group }: { item: ConversationSummaryItem; group: GroupName }) {
  const duration = formatDuration(item.started_at, item.ended_at);
  return (
    <Link
      to="/history/$id"
      params={{ id: item.id }}
      className="flex gap-4 rounded-[calc(var(--radius))] border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4 transition-colors hover:border-[hsl(var(--primary))]/40"
    >
      <div className="min-w-0 flex-1">
        <p className="text-[15px] leading-snug font-medium tracking-tight text-[hsl(var(--foreground))]">
          {item.summary ?? 'No summary yet — the conversation may still be in progress.'}
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[hsl(var(--muted-foreground))]">
          <span className="font-mono">{formatRowTime(item.started_at, group)}</span>
          {duration ? (
            <span className="inline-flex items-center gap-1">
              <Clock className="h-3 w-3" /> {duration}
            </span>
          ) : null}
          <span>
            {item.message_count} {item.message_count === 1 ? 'message' : 'messages'}
          </span>
        </div>
      </div>
      <ChevronRight
        className="mt-1 h-4 w-4 flex-none text-[hsl(var(--muted-foreground))]"
        aria-hidden
      />
    </Link>
  );
}

type GroupName = 'Today' | 'This week' | 'Earlier';
interface Group {
  group: GroupName;
  items: ConversationSummaryItem[];
}

function groupByDate(items: ConversationSummaryItem[]): Group[] {
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const oneWeekAgo = startOfToday - 7 * 24 * 60 * 60 * 1000;

  const today: ConversationSummaryItem[] = [];
  const thisWeek: ConversationSummaryItem[] = [];
  const earlier: ConversationSummaryItem[] = [];

  for (const item of items) {
    const t = Date.parse(item.started_at);
    if (Number.isNaN(t)) {
      earlier.push(item);
      continue;
    }
    if (t >= startOfToday) today.push(item);
    else if (t >= oneWeekAgo) thisWeek.push(item);
    else earlier.push(item);
  }

  return [
    today.length ? ({ group: 'Today', items: today } as Group) : null,
    thisWeek.length ? ({ group: 'This week', items: thisWeek } as Group) : null,
    earlier.length ? ({ group: 'Earlier', items: earlier } as Group) : null,
  ].filter((g): g is Group => g !== null);
}

/**
 * Per-group date/time format mirroring the design's history list:
 *   - Today  → time only ("2:41 PM")
 *   - This week → weekday + time ("Tue · 9:15 AM")
 *   - Earlier → month + day ("Apr 18")
 *
 * The compact format is the row metadata, not the headline — the
 * summary copy is what users actually scan for.
 */
function formatRowTime(iso: string, group: GroupName): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  if (group === 'Today') {
    return d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
  }
  if (group === 'This week') {
    const weekday = d.toLocaleDateString(undefined, { weekday: 'short' });
    const time = d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
    return `${weekday} · ${time}`;
  }
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function formatShortDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function formatDuration(startedAt: string, endedAt: string | null): string | null {
  if (!endedAt) return null;
  const start = Date.parse(startedAt);
  const end = Date.parse(endedAt);
  if (Number.isNaN(start) || Number.isNaN(end) || end <= start) return null;
  const totalSeconds = Math.round((end - start) / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes === 0) return `${seconds}s`;
  return `${minutes}m ${String(seconds).padStart(2, '0')}s`;
}
