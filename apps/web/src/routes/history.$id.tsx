import { Link, createFileRoute, redirect, useParams } from '@tanstack/react-router';
import { useQuery } from '@tanstack/react-query';

import { apiFetch, ApiError } from '@/lib/api';
import { supabase } from '@/lib/supabase';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

/**
 * Wire shape of `GET /conversations/{id}`. Mirrors
 * `ConversationDetailResponse` in `apps/api/api/routes.py`.
 */
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
      <header className="flex items-center justify-between border-b border-[hsl(var(--border))] px-6 py-3">
        <h1 className="text-lg font-semibold">Conversation</h1>
        <nav className="flex items-center gap-2">
          <Button asChild variant="link" size="sm">
            <Link to="/history">Back to history</Link>
          </Button>
          <Button asChild variant="link" size="sm">
            <Link to="/">Talk</Link>
          </Button>
        </nav>
      </header>
      <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-4 px-4 py-6">
        <ConversationView id={id} />
      </main>
    </div>
  );
}

/**
 * Renders the ordered transcript with role-styled bubbles and
 * timestamps. Tool messages are styled distinctly so they read as a
 * third message type rather than a malformed assistant turn.
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

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{formatTimestamp(data.started_at)}</CardTitle>
          <CardDescription>
            {data.summary ?? 'No summary yet — the conversation may still be in progress.'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="flex flex-col gap-2 text-sm">
            {data.messages.map((m) => (
              <MessageBubble key={m.id} message={m} />
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}

function MessageBubble({ message }: { message: MessageItem }) {
  if (message.role === 'tool') {
    return (
      <li className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40 px-3 py-2">
        <div className="flex items-center justify-between gap-2">
          <span className="flex items-center gap-2">
            <Badge variant="outline" className="text-[10px] uppercase tracking-wide">
              tool
            </Badge>
            <code className="font-mono text-xs">{message.tool_name ?? 'unknown'}</code>
          </span>
          <time className="text-[10px] text-[hsl(var(--muted-foreground))]">
            {formatTimestamp(message.created_at)}
          </time>
        </div>
        {message.tool_args ? (
          <pre className="mt-1 overflow-x-auto rounded bg-[hsl(var(--background))] p-2 font-mono text-xs">
            {JSON.stringify(message.tool_args, null, 2)}
          </pre>
        ) : null}
        {message.tool_result !== null && message.tool_result !== undefined ? (
          <pre className="mt-1 overflow-x-auto rounded bg-[hsl(var(--background))] p-2 font-mono text-xs">
            {typeof message.tool_result === 'string'
              ? message.tool_result
              : JSON.stringify(message.tool_result, null, 2)}
          </pre>
        ) : null}
      </li>
    );
  }
  const isUser = message.role === 'user';
  return (
    <li
      data-role={message.role}
      className={cn(
        'rounded-md px-3 py-2',
        isUser
          ? 'bg-[hsl(var(--accent))] text-[hsl(var(--accent-foreground))]'
          : 'bg-[hsl(var(--secondary))] text-[hsl(var(--secondary-foreground))]',
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <Badge
          variant={isUser ? 'default' : 'secondary'}
          className="text-[10px] uppercase tracking-wide"
        >
          {message.role}
        </Badge>
        <time className="text-[10px] text-[hsl(var(--muted-foreground))]">
          {formatTimestamp(message.created_at)}
        </time>
      </div>
      <p className="mt-1 whitespace-pre-wrap">{message.content}</p>
    </li>
  );
}

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}
