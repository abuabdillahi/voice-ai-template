import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

/**
 * Wire shape of the `find_clinician` tool's success and error
 * payloads. Mirrors `core.clinician.find_clinics` (success) and the
 * failure-taxonomy rows (error). The frontend parses the tool result
 * JSON and discriminates by the presence of the `error` key.
 */
export type FindClinicianResult =
  | {
      specialist_label: string;
      location_resolved: string;
      radius_km: number;
      results: Array<{
        name: string;
        address: string;
        phone: string;
        url: string;
        distance_km: number;
      }>;
      count: number;
    }
  | { error: string };

interface ClinicianSuggestionsProps {
  /**
   * Raw tool-call result. `null` represents the in-flight state (the
   * tool dispatched, not yet returned). Strings are JSON-encoded
   * payloads from the agent worker.
   */
  result: string | null;
}

/**
 * Renders the result of a `find_clinician` tool call as a card list.
 *
 * Four states keyed off the parsed payload:
 *
 * 1. **In-flight** — `result === null`. Shows a spinner and the
 *    verbal-filler echo so the user has visual feedback during the
 *    upstream HTTP latency.
 * 2. **Success** — payload has `results`. Card list ordered by
 *    distance ascending; each card carries name, address, a
 *    `tel:` phone link (when populated), distance, and a "view on
 *    OpenStreetMap" link.
 * 3. **Zero-results** — payload has `error` matching the failure-
 *    taxonomy row #6 (50 km radius exhausted). Renders the error
 *    string verbatim with no card list.
 * 4. **Error** — any other `error` payload (network error, unknown
 *    condition, empty location). Renders the error string verbatim.
 *
 * The component is reused on the live talk page (via the
 * `lk.tool-calls` topic subscriber's branch on
 * `name === 'find_clinician'`) and on `/history/:id` (rendered from
 * the persisted `messages.tool_args` and `messages.tool_result` JSON
 * columns). The footer carries the OSM ODbL attribution required by
 * the upstream license.
 */
export function ClinicianSuggestions({ result }: ClinicianSuggestionsProps) {
  if (result === null) {
    return (
      <div
        className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40 px-3 py-3"
        data-testid="clinician-suggestions"
        data-state="in-flight"
      >
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="text-[10px] uppercase tracking-wide">
            tool · find_clinician
          </Badge>
          <span
            aria-hidden
            className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent"
          />
          <span className="text-sm">Searching around your area…</span>
        </div>
        <Footer />
      </div>
    );
  }

  let parsed: FindClinicianResult | null = null;
  try {
    parsed = JSON.parse(result) as FindClinicianResult;
  } catch {
    parsed = null;
  }

  if (parsed === null) {
    return (
      <div
        className="rounded-md border border-[hsl(var(--destructive))]/40 bg-[hsl(var(--destructive))]/5 px-3 py-3"
        data-testid="clinician-suggestions"
        data-state="error"
      >
        <p className="text-sm">I couldn&apos;t read the response from the maps service.</p>
        <Footer />
      </div>
    );
  }

  if ('error' in parsed) {
    const isZeroResults =
      parsed.error.includes('within 50 km') ||
      parsed.error.includes('Your best bet is to search Google Maps');
    return (
      <div
        className={cn(
          'rounded-md border px-3 py-3',
          isZeroResults
            ? 'border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40'
            : 'border-[hsl(var(--destructive))]/40 bg-[hsl(var(--destructive))]/5',
        )}
        data-testid="clinician-suggestions"
        data-state={isZeroResults ? 'zero-results' : 'error'}
      >
        <p className="text-sm">{parsed.error}</p>
        <Footer />
      </div>
    );
  }

  const sorted = parsed.results.slice().sort((a, b) => a.distance_km - b.distance_km);
  return (
    <div
      className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-3"
      data-testid="clinician-suggestions"
      data-state="success"
    >
      <header className="mb-2">
        <h3 className="text-sm font-semibold">
          {parsed.specialist_label} near {parsed.location_resolved} — within {parsed.radius_km} km
        </h3>
        <p className="text-[11px] text-[hsl(var(--muted-foreground))]">
          Double-check the details before calling — OSM data can be out of date.
        </p>
      </header>
      <ul className="flex flex-col gap-2">
        {sorted.map((clinic) => (
          <li
            key={clinic.url}
            className="rounded border border-[hsl(var(--border))]/60 bg-[hsl(var(--muted))]/30 px-3 py-2"
            data-testid="clinician-card"
          >
            <p className="text-sm font-medium">{clinic.name}</p>
            <p className="text-xs text-[hsl(var(--muted-foreground))]">{clinic.address}</p>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
              {clinic.phone ? (
                <a
                  href={`tel:${clinic.phone}`}
                  className="text-[hsl(var(--primary))] underline-offset-2 hover:underline"
                >
                  {clinic.phone}
                </a>
              ) : null}
              <span className="text-[hsl(var(--muted-foreground))]">
                {clinic.distance_km.toFixed(1)} km
              </span>
              <a
                href={clinic.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[hsl(var(--primary))] underline-offset-2 hover:underline"
              >
                view on OpenStreetMap
              </a>
            </div>
          </li>
        ))}
      </ul>
      <Footer />
    </div>
  );
}

function Footer() {
  return (
    <p
      className="mt-2 text-[10px] text-[hsl(var(--muted-foreground))]"
      data-testid="clinician-attribution"
    >
      Sourced from{' '}
      <a
        href="https://www.openstreetmap.org/copyright"
        target="_blank"
        rel="noopener noreferrer"
        className="underline-offset-2 hover:underline"
      >
        © OpenStreetMap contributors
      </a>
    </p>
  );
}
