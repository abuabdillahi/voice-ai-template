import { Link, createFileRoute, redirect } from '@tanstack/react-router';
import { useQuery } from '@tanstack/react-query';

import { apiFetch } from '@/lib/api';
import { supabase } from '@/lib/supabase';
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';

/**
 * Wire shape of `GET /conversations`. Mirrors `ConversationsListResponse`
 * in `apps/api/api/routes.py`. Kept inline (rather than imported from
 * the generated `types.gen.ts`) for the same reason `MemorySidebar`
 * does — the indirection adds import noise without payoff while this
 * is the only consumer.
 */
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

export const Route = createFileRoute('/history')({
  beforeLoad: async () => {
    const { data } = await supabase.auth.getSession();
    if (!data.session) {
      throw redirect({ to: '/sign-in' });
    }
  },
  component: HistoryRoute,
});

function HistoryRoute() {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex items-center justify-between border-b border-[hsl(var(--border))] px-6 py-3">
        <h1 className="text-lg font-semibold">Conversation history</h1>
        <nav className="flex items-center gap-2">
          <Button asChild variant="link" size="sm">
            <Link to="/">Talk</Link>
          </Button>
          <Button asChild variant="link" size="sm">
            <Link to="/settings">Settings</Link>
          </Button>
        </nav>
      </header>
      <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-4 px-4 py-6">
        <HistoryList />
      </main>
    </div>
  );
}

/**
 * Past-conversations list view. Each row links to the detail route.
 *
 * The empty state is reassuring rather than apologetic — same
 * principle as `MemorySidebar`. A user who has just signed up should
 * see "your conversations will appear here" rather than an error or
 * a blank pane.
 */
export function HistoryList() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['conversations'],
    queryFn: () => apiFetch<ConversationsListResponse>('/conversations'),
    staleTime: 10_000,
  });

  if (isLoading) {
    return <p className="text-sm text-[hsl(var(--muted-foreground))]">Loading…</p>;
  }
  if (isError) {
    return (
      <p className="text-sm text-[hsl(var(--destructive))]">
        Couldn&apos;t load your conversations right now.
      </p>
    );
  }
  const items = data?.conversations ?? [];
  if (items.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">No conversations yet</CardTitle>
          <CardDescription>
            Conversations you have with the assistant will appear here.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }
  return (
    <ul className="flex flex-col gap-3">
      {items.map((item) => (
        <li key={item.id}>
          <Link
            to="/history/$id"
            params={{ id: item.id }}
            className="block rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4 transition-colors hover:bg-[hsl(var(--accent))]"
          >
            <div className="flex items-center justify-between gap-4">
              <span className="text-sm font-medium">{formatStartedAt(item.started_at)}</span>
              <span className="text-xs text-[hsl(var(--muted-foreground))]">
                {item.message_count} {item.message_count === 1 ? 'message' : 'messages'}
              </span>
            </div>
            <p className="mt-2 text-sm text-[hsl(var(--muted-foreground))]">
              {item.summary ?? 'No summary yet.'}
            </p>
          </Link>
        </li>
      ))}
    </ul>
  );
}

function formatStartedAt(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}
