import { AlertTriangle, Check, Phone } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import type { SessionEndSignal } from '@/lib/livekit-session-end';
import { cn } from '@/lib/utils';

type Tier = 'emergent' | 'urgent' | 'routine' | 'unknown';

interface TierMeta {
  label: string;
  badgeClass: string;
  title: string;
  body: string;
  color: string;
  bg: string;
  border: string;
  Icon: typeof Phone;
}

const TIER_META: Record<Exclude<Tier, 'unknown'>, TierMeta> = {
  emergent: {
    label: 'Emergent',
    badgeClass:
      'bg-[hsl(var(--tier-emergent-soft))] text-[hsl(var(--tier-emergent))] border border-[hsl(var(--tier-emergent-border))]',
    title: 'Call your local emergency number now.',
    body: 'Some of what you described needs in-person care immediately. This tool can’t help further.',
    color: 'hsl(var(--tier-emergent))',
    bg: 'hsl(var(--tier-emergent-soft))',
    border: 'hsl(var(--tier-emergent-border))',
    Icon: AlertTriangle,
  },
  urgent: {
    label: 'Urgent',
    badgeClass:
      'bg-[hsl(var(--tier-urgent-soft))] text-[hsl(var(--tier-urgent))] border border-[hsl(var(--tier-urgent-border))]',
    title: 'Please seek urgent care today.',
    body: 'Your symptoms are outside what self-care should handle alone. Reach out to a clinician today.',
    color: 'hsl(var(--tier-urgent))',
    bg: 'hsl(var(--tier-urgent-soft))',
    border: 'hsl(var(--tier-urgent-border))',
    Icon: Phone,
  },
  routine: {
    label: 'Routine',
    badgeClass:
      'bg-[hsl(var(--tier-routine-soft))] text-[hsl(var(--tier-routine))] border border-[hsl(var(--tier-routine-border))]',
    title: 'Conversation ended.',
    body: 'Sarjy has ended the session. Your transcript and triage chart are saved below.',
    color: 'hsl(var(--tier-routine))',
    bg: 'hsl(var(--tier-routine-soft))',
    border: 'hsl(var(--tier-routine-border))',
    Icon: Check,
  },
};

const FALLBACK_META: TierMeta = {
  label: 'Ended',
  badgeClass:
    'bg-[hsl(var(--muted))] text-[hsl(var(--muted-foreground))] border border-[hsl(var(--border))]',
  title: 'Conversation ended.',
  body: 'Sarjy has ended the session.',
  color: 'hsl(var(--muted-foreground))',
  bg: 'hsl(var(--muted))',
  border: 'hsl(var(--border))',
  Icon: Check,
};

const USER_ENDED_META: TierMeta = {
  label: 'Ended',
  badgeClass:
    'bg-[hsl(var(--tier-routine-soft))] text-[hsl(var(--tier-routine))] border border-[hsl(var(--tier-routine-border))]',
  title: 'Conversation ended.',
  body: "Here's what we covered. The transcript and triage chart are frozen below — open History if you'd like to revisit later.",
  color: 'hsl(var(--tier-routine))',
  bg: 'hsl(var(--tier-routine-soft))',
  border: 'hsl(var(--tier-routine-border))',
  Icon: Check,
};

/**
 * Tier-coded banner shown at end-of-session. Renders as a layered card
 * *above* the now-frozen transcript instead of a takeover replacement
 * — the user keeps the conversation artifact in view while reading
 * the routing copy.
 *
 * No Reconnect / Try-again affordance lives here, by design: the
 * safety screen has just routed the user away from the tool. The only
 * way out is the page chrome (Sign out / History).
 *
 * The two assertion-load-bearing strings preserved across the
 * redesign are "This conversation has ended" (for emergent + urgent;
 * regression anchor against the prior "This call has ended" wording),
 * and the verbatim tier-1/tier-2 routing scripts.
 */
export function EndOfConversationCard({ signal }: { signal: SessionEndSignal }) {
  const isUserEnded = signal.reason === 'user_ended';
  const tier = (
    signal.tier === 'emergent' || signal.tier === 'urgent' || signal.tier === 'routine'
      ? signal.tier
      : 'unknown'
  ) as Tier;
  const meta = isUserEnded ? USER_ENDED_META : tier === 'unknown' ? FALLBACK_META : TIER_META[tier];

  // The card-level `aria-label` keeps the regression anchor that the
  // surface still reads as "Conversation ended" to assistive tech.
  const headlineForRegression =
    tier === 'emergent' || tier === 'urgent' ? 'This conversation has ended' : 'Conversation ended';

  return (
    <section
      role="region"
      aria-label="Conversation ended"
      className="overflow-hidden rounded-[calc(var(--radius))] border bg-[var(--banner-bg)] sm:[border-left-width:4px]"
      style={{
        ['--banner-bg' as string]: meta.bg,
        borderColor: meta.border,
        borderLeftColor: meta.color,
      }}
    >
      {/* Header strip — badge on the left, the regression-anchor
          headline pushed to the right. The strip is the mobile tier
          banner pattern from the handoff design; on desktop the icon
          slots in next to the badge so the same row carries through
          the breakpoints. */}
      <div
        className="flex items-center gap-3 border-b px-4 py-2.5 sm:px-6 sm:py-3"
        style={{ borderBottomColor: meta.border }}
      >
        <div
          aria-hidden
          className="hidden h-10 w-10 flex-none items-center justify-center rounded-[10px] border bg-[hsl(var(--card))] sm:flex"
          style={{ borderColor: meta.border, color: meta.color }}
        >
          <meta.Icon className="h-5 w-5" />
        </div>
        <Badge variant="outline" className={cn('rounded-full', meta.badgeClass)}>
          {meta.label}
        </Badge>
        <span className="ml-auto text-[11px] text-[hsl(var(--muted-foreground))] sm:text-xs">
          {headlineForRegression}
        </span>
      </div>
      <div className="px-4 py-3 sm:px-6 sm:py-4">
        <p
          className="mb-1 font-serif text-[22px] leading-[1.25] tracking-tight"
          style={{ color: meta.color }}
        >
          {meta.title}
        </p>
        <p className="text-[13.5px] leading-relaxed text-[hsl(var(--foreground))] sm:text-[14px]">
          {meta.body}
        </p>
        {/* The "next step above takes priority" disclaimer is the
            desktop tier banner's safety footer — the mobile artboard
            drops it; the routing copy above already carries the
            load-bearing message. */}
        <p className="mt-3 hidden text-xs text-[hsl(var(--muted-foreground))] sm:block">
          Sarjy is an educational tool, not a doctor. The next step above takes priority over
          anything Sarjy has discussed in this session.
        </p>
      </div>
    </section>
  );
}
