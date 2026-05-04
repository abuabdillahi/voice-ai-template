import { useQuery } from '@tanstack/react-query';

import { apiFetch } from '@/lib/api';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

/**
 * Wire shape of `GET /preferences`. Mirrors `PreferencesResponse` in
 * `apps/api/api/routes.py`. The generated `types.gen.ts` exports an
 * equivalent type — this local interface is duplicated here for now
 * because the talk page is the only consumer and the indirection adds
 * import noise without payoff. When a second route reads the same
 * shape we'll switch to the generated one.
 */
interface PreferencesResponse {
  preferences: Record<string, unknown>;
}

/**
 * Wire shape of `GET /memories/recent`. Mirrors `MemoriesResponse` in
 * the API. Each memory carries an opaque mem0 id (kept as a stable
 * react key) and the memory's natural-language content.
 */
interface MemoryItem {
  id: string;
  content: string;
}
interface MemoriesResponse {
  memories: MemoryItem[];
}

/**
 * "What I remember about you" sidebar.
 *
 * Renders two stacked cards: the user's structured preferences and
 * the most recent episodic memories from mem0. Both poll on a 10s
 * cadence so something the agent saved mid-conversation appears
 * without a manual refresh.
 *
 * Empty states are deliberately reassuring rather than apologetic —
 * the sidebar exists to make the memory layer *visibly present* from
 * minute zero, even before the user has stated anything to remember.
 */
export function MemorySidebar() {
  return (
    <div className="flex flex-col gap-3">
      <PreferencesCard />
      <RecentMemoriesCard />
    </div>
  );
}

function PreferencesCard() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['preferences'],
    queryFn: () => apiFetch<PreferencesResponse>('/preferences'),
    refetchInterval: 10_000,
    staleTime: 5_000,
  });

  const entries = data ? Object.entries(data.preferences) : [];

  return (
    <Card aria-label="What I remember about you">
      <CardHeader>
        <CardTitle className="text-base">What I remember about you</CardTitle>
        <CardDescription>Saved preferences sync across devices.</CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <p className="text-sm text-[hsl(var(--muted-foreground))]">Loading…</p>
        ) : isError ? (
          <p className="text-sm text-[hsl(var(--destructive))]">
            Couldn&apos;t load preferences right now.
          </p>
        ) : entries.length === 0 ? (
          <p className="text-sm text-[hsl(var(--muted-foreground))]">
            I&apos;ll remember things you tell me here.
          </p>
        ) : (
          <ul className="flex flex-col gap-2 text-sm">
            {entries.map(([key, value]) => (
              <li
                key={key}
                className="flex items-baseline justify-between gap-3 border-b border-[hsl(var(--border))] pb-2 last:border-b-0 last:pb-0"
              >
                <span className="text-[hsl(var(--muted-foreground))] font-medium">{key}</span>
                <span className="font-mono text-xs">{formatValue(value)}</span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

/**
 * Lists the user's most recent episodic memories, populated by
 * mem0-backed `remember` tool calls during conversations.
 *
 * Refetched on the same 10-second cadence as preferences so the panel
 * reflects mid-conversation `remember` calls without a page reload.
 * The empty-state copy nudges the user toward what kinds of facts
 * will land here, since the layer is invisible until they mention
 * something the agent decides to save.
 */
function RecentMemoriesCard() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['memories', 'recent'],
    queryFn: () => apiFetch<MemoriesResponse>('/memories/recent'),
    refetchInterval: 10_000,
    staleTime: 5_000,
  });

  const memories = data?.memories ?? [];

  return (
    <Card aria-label="Recent memories">
      <CardHeader>
        <CardTitle className="text-base">Recent memories</CardTitle>
        <CardDescription>Things you&apos;ve mentioned in conversation.</CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <p className="text-sm text-[hsl(var(--muted-foreground))]">Loading…</p>
        ) : isError ? (
          <p className="text-sm text-[hsl(var(--destructive))]">
            Couldn&apos;t load memories right now.
          </p>
        ) : memories.length === 0 ? (
          <p className="text-sm text-[hsl(var(--muted-foreground))]">
            Things you mention in conversation will appear here.
          </p>
        ) : (
          <ul className="flex flex-col gap-2 text-sm">
            {memories.map((m) => (
              <li
                key={m.id}
                className="border-b border-[hsl(var(--border))] pb-2 last:border-b-0 last:pb-0"
              >
                {m.content}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

/**
 * Render a `jsonb` value as a short string. Strings come through as
 * themselves; everything else is JSON-stringified so structured values
 * (rare today, expected as the schema grows) still render readably.
 */
function formatValue(value: unknown): string {
  if (typeof value === 'string') return value;
  if (value === null || value === undefined) return '';
  return JSON.stringify(value);
}
