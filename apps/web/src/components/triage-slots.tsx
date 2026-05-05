import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { TRIAGE_SLOTS } from '@/lib/livekit-triage-state';

interface TriageSlotsProps {
  slots: Record<string, string>;
}

/**
 * OPQRST slot panel. Renders one row per canonical slot in
 * :data:`TRIAGE_SLOTS`; slots not yet disclosed show a placeholder so
 * the user can see what the agent has gathered and what is still
 * outstanding.
 */
export function TriageSlots({ slots }: TriageSlotsProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">What I've gathered</CardTitle>
        <CardDescription>
          Updates as we talk. Empty rows are slots I have not asked about yet.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <dl className="flex flex-col gap-2 text-sm">
          {TRIAGE_SLOTS.map((slot) => {
            const value = slots[slot.key]?.trim();
            return (
              <div
                key={slot.key}
                className="flex items-baseline justify-between gap-3 border-b border-[hsl(var(--border))]/40 pb-1.5 last:border-b-0 last:pb-0"
                data-testid={`triage-slot-${slot.key}`}
              >
                <dt className="font-medium text-[hsl(var(--muted-foreground))]">{slot.label}</dt>
                <dd className={value ? '' : 'text-[hsl(var(--muted-foreground))] italic'}>
                  {value || 'not yet disclosed'}
                </dd>
              </div>
            );
          })}
        </dl>
      </CardContent>
    </Card>
  );
}
