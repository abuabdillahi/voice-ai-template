import { Link, useNavigate } from '@tanstack/react-router';

import { supabase } from '@/lib/supabase';
import { TalkPage } from '@/components/talk-page';
import { Button } from '@/components/ui/button';

/**
 * The five MVP conditions surfaced in the scope statement. The agent's
 * system prompt encodes the same scope (see `apps/agent/agent/session.py`
 * SYSTEM_PROMPT) — both lists are derived from the same source of
 * truth (`packages/core/core/conditions.py`). The labels here are the
 * spoken-language framing the user sees before clicking the talk
 * button; the agent reinforces them in its opening spoken disclaimer.
 */
export const IN_SCOPE_CONDITIONS = [
  'Carpal tunnel syndrome',
  'Computer vision syndrome (digital eye strain)',
  'Tension-type headache',
  'Upper trapezius / "text neck" strain',
  'Lumbar strain from prolonged sitting',
];

/**
 * Triage home page body. Extracted from the route file so the test
 * suite can render it without mocking out `@tanstack/react-router`'s
 * `createFileRoute`.
 *
 * Layout: educational-tool disclaimer banner, then a scope statement
 * naming the in-scope conditions, then the talk button. The memory
 * sidebar from the template's home page is intentionally absent —
 * triage is single-session and the cross-session "what I remember
 * about you" surface is an avoidable hallucination risk for a
 * medical-adjacent product.
 */
export function TriageHome() {
  const navigate = useNavigate();

  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex items-center justify-between border-b border-[hsl(var(--border))] px-6 py-3">
        <h1 className="text-lg font-semibold">Ergo Triage</h1>
        <nav className="flex items-center gap-2">
          <Button asChild variant="link" size="sm">
            <Link to="/history">History</Link>
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={async () => {
              await supabase.auth.signOut();
              void navigate({ to: '/sign-in' });
            }}
          >
            Sign out
          </Button>
        </nav>
      </header>
      <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-4 py-6">
        <DisclaimerBanner />
        <ScopeStatement />
        <TalkPage />
      </main>
    </div>
  );
}

export function DisclaimerBanner() {
  return (
    <section
      role="region"
      aria-label="Educational tool disclaimer"
      className="rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900"
    >
      <p className="font-semibold">This is an educational tool, not a doctor.</p>
      <p className="mt-1">
        Ergo Triage helps you think about office-strain symptoms and what to try first. It is not a
        substitute for professional medical advice. If something feels urgent, call your local
        emergency number or go to urgent care.
      </p>
    </section>
  );
}

export function ScopeStatement() {
  return (
    <section
      role="region"
      aria-label="What this tool can help with"
      className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40 px-4 py-3 text-sm"
    >
      <p className="font-medium">What I can help with</p>
      <ul className="mt-1 list-disc space-y-0.5 pl-5">
        {IN_SCOPE_CONDITIONS.map((condition) => (
          <li key={condition}>{condition}</li>
        ))}
      </ul>
      <p className="mt-2 text-[hsl(var(--muted-foreground))]">
        Anything outside these — including medications, mental health, pregnancy, paediatric, and
        post-surgical questions — I will route you to a more appropriate resource.
      </p>
    </section>
  );
}
