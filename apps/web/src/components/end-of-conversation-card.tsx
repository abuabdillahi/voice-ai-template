import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import type { SessionEndSignal } from '@/lib/livekit-session-end';

/**
 * Tier-aware routing copy shown after the safety screen ends the
 * conversation. The Sign-out / History links in the page chrome are
 * the only way out — there is no Reconnect affordance, by design:
 * the safety screen has just routed the user away from the tool.
 */
export function EndOfConversationCard({ signal }: { signal: SessionEndSignal }) {
  const tier = signal.tier;
  const headline =
    tier === 'emergent' || tier === 'urgent' ? 'This conversation has ended' : 'Conversation ended';
  const routing =
    tier === 'emergent'
      ? 'Call your local emergency number now.'
      : tier === 'urgent'
        ? 'Please seek urgent care today.'
        : 'Sarjy has ended the session.';

  return (
    <Card
      role="region"
      aria-label="Conversation ended"
      className="border-amber-300 bg-amber-50 text-amber-900"
    >
      <CardHeader>
        <CardTitle>{headline}</CardTitle>
        <CardDescription className="text-amber-900/80">{routing}</CardDescription>
      </CardHeader>
      <CardContent>
        <p className="text-sm">
          Sarjy is an educational tool, not a doctor. The next step above takes priority over
          anything Sarjy has discussed in this session.
        </p>
      </CardContent>
    </Card>
  );
}
