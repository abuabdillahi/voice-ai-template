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
 * "What I remember about you" sidebar.
 *
 * Renders the authenticated user's structured preferences as a list
 * of labelled key:value rows. Polls `GET /preferences` every 10
 * seconds so a preference saved by the agent mid-conversation appears
 * without a manual refresh.
 *
 * Empty state is deliberately reassuring rather than apologetic — the
 * sidebar exists to make the memory layer *visibly present* from
 * minute zero, even before the user has stated anything to remember.
 */
export function MemorySidebar() {
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
 * Render a `jsonb` value as a short string. Strings come through as
 * themselves; everything else is JSON-stringified so structured values
 * (rare today, expected as the schema grows) still render readably.
 */
function formatValue(value: unknown): string {
  if (typeof value === 'string') return value;
  if (value === null || value === undefined) return '';
  return JSON.stringify(value);
}
