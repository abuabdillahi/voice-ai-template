import { TRIAGE_SLOTS } from '@/lib/livekit-triage-state';
import { cn } from '@/lib/utils';

interface TriageSlotsProps {
  slots: Record<string, string>;
  /** When `true`, the panel renders a "snapshot frozen" footer (post-session). */
  frozen?: boolean;
}

/**
 * OPQRST slot panel. Renders one row per canonical slot in
 * :data:`TRIAGE_SLOTS`; slots not yet disclosed show a placeholder so
 * the user can see what the agent has gathered and what is still
 * outstanding.
 *
 * Visual treatment:
 *  - Header carries a progress bar (`filled / total`) so the user can
 *    feel the conversation moving.
 *  - The first not-yet-disclosed slot gets a left accent bar and a
 *    subtle teal tint, plus an "Asking next" hint — this turns a
 *    static checklist into a live interaction surface.
 *  - Each clinical label carries its plain-English subtitle inline so
 *    a non-clinical user can decode "Onset" / "Quality" / "Radiation"
 *    without breaking eye contact with the conversation.
 */
export function TriageSlots({ slots, frozen = false }: TriageSlotsProps) {
  const filled = TRIAGE_SLOTS.filter((s) => slots[s.key]?.trim()).length;
  const total = TRIAGE_SLOTS.length;
  const pct = Math.round((filled / total) * 100);
  const firstEmptyIndex = TRIAGE_SLOTS.findIndex((s) => !slots[s.key]?.trim());

  return (
    <section
      aria-label="What I've gathered"
      className="overflow-hidden rounded-[calc(var(--radius))] border border-[hsl(var(--border))] bg-[hsl(var(--card))]"
    >
      <div className="px-[18px] pt-4 pb-[14px]">
        <div className="mb-3 flex items-baseline justify-between">
          <h3 className="text-[15px] font-semibold tracking-tight">What I&apos;ve gathered</h3>
          <span className="font-mono text-xs text-[hsl(var(--muted-foreground))]">
            {filled}/{total}
          </span>
        </div>
        <div
          className="relative h-1.5 overflow-hidden rounded-full bg-[hsl(var(--muted))]"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={total}
          aria-valuenow={filled}
        >
          <div
            className="absolute inset-y-0 left-0 transition-[width] duration-500"
            style={{
              width: `${pct}%`,
              background: 'linear-gradient(90deg, hsl(var(--primary)), hsl(var(--primary-strong)))',
            }}
          />
        </div>
      </div>
      <ul className="m-0 list-none p-0">
        {TRIAGE_SLOTS.map((slot, i) => {
          const value = slots[slot.key]?.trim();
          const isNext = !value && i === firstEmptyIndex && !frozen;
          return (
            <li
              key={slot.key}
              data-testid={`triage-slot-${slot.key}`}
              className={cn(
                'relative px-[18px] py-3',
                i < TRIAGE_SLOTS.length - 1 && 'border-b border-[hsl(var(--border))]',
                isNext && 'bg-[hsl(var(--primary-soft)/0.5)]',
              )}
            >
              {isNext ? (
                <span
                  aria-hidden
                  className="absolute inset-y-0 left-0 w-[3px] bg-[hsl(var(--primary))]"
                />
              ) : null}
              <div className={cn('flex items-baseline justify-between gap-3', value && 'mb-1')}>
                <div className="flex min-w-0 items-baseline gap-2">
                  <dt
                    className={cn(
                      'text-[13.5px] font-semibold',
                      value
                        ? 'text-[hsl(var(--foreground))]'
                        : isNext
                          ? 'text-[hsl(var(--primary-soft-fg))]'
                          : 'text-[hsl(var(--muted-foreground))]',
                    )}
                  >
                    {slot.label}
                  </dt>
                  <span className="text-[11.5px] text-[hsl(var(--muted-foreground))]">
                    {slot.plain}
                  </span>
                </div>
                {isNext ? (
                  <span className="text-[11px] font-medium text-[hsl(var(--primary-soft-fg))]">
                    Asking next →
                  </span>
                ) : null}
              </div>
              <dd
                className={cn(
                  'text-[13.5px] leading-snug',
                  value
                    ? 'text-[hsl(var(--foreground))]'
                    : 'italic text-[hsl(var(--muted-foreground))]',
                )}
              >
                {value || 'not yet disclosed'}
              </dd>
            </li>
          );
        })}
      </ul>
      {frozen ? (
        <div className="bg-[hsl(var(--muted))] px-[18px] py-3 text-xs text-[hsl(var(--muted-foreground))]">
          Snapshot frozen at end of session.
        </div>
      ) : null}
    </section>
  );
}
