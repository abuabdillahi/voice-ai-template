import { AppHeader } from '@/components/app-header';
import { TalkPage } from '@/components/talk-page';

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
 * limber home page body. Renders the app-wide header with Talk/History
 * nav and the talk surface beneath. The pre-connect mode of the talk
 * surface owns limber's marketing hero, the Brook "Meet your assistant"
 * card, and the safety disclaimer so the safety surface sits where the
 * user is making the decision instead of as a wall of text.
 */
export function LimberHome() {
  return (
    <div className="flex min-h-screen flex-col">
      <AppHeader active="talk" />
      <main className="flex-1">
        <TalkPage />
      </main>
    </div>
  );
}

/**
 * Standalone disclaimer banner. The talk page now owns the visible
 * disclaimer surface (see `talk-page.tsx#DisclaimerSafetyCard`) — this
 * component remains for direct re-use by routes/tests that want the
 * load-bearing copy in isolation.
 */
export function DisclaimerBanner() {
  return (
    <section
      role="region"
      aria-label="Educational tool disclaimer"
      className="rounded-md border border-[hsl(var(--amber-soft-border))] bg-[hsl(var(--amber-soft))] px-4 py-3 text-sm text-[hsl(var(--amber-soft-body))]"
    >
      <p className="font-semibold text-[hsl(var(--amber-soft-fg-strong))]">
        I&apos;m an educational tool, not a doctor.
      </p>
      <p className="mt-1">
        limber helps you think about office-strain symptoms and what to try first. It is not a
        substitute for professional medical advice. If something feels urgent, call your local
        emergency number or go to urgent care.
      </p>
    </section>
  );
}

/**
 * Standalone scope statement. Same lifecycle as `DisclaimerBanner` —
 * the talk page renders an equivalent treatment inline; this is the
 * direct-render form used by tests and any route that wants the
 * literal in-scope list.
 */
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
