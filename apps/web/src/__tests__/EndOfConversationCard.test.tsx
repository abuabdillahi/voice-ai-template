import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { EndOfConversationCard } from '@/components/end-of-conversation-card';

describe('EndOfConversationCard', () => {
  it('renders the tier-1 emergency routing copy', () => {
    render(<EndOfConversationCard signal={{ reason: 'escalation', tier: 'emergent' }} />);
    // The literal phone-call instruction inside the script is correct
    // English ("call" is the verb for "use the telephone") and stays
    // unchanged by the user-facing rename.
    expect(screen.getByText(/call your local emergency number now/i)).toBeInTheDocument();
  });

  it('renders the tier-2 urgent-care routing copy', () => {
    render(<EndOfConversationCard signal={{ reason: 'escalation', tier: 'urgent' }} />);
    expect(screen.getByText(/please seek urgent care today/i)).toBeInTheDocument();
  });

  it('does NOT render a Reconnect button', () => {
    render(<EndOfConversationCard signal={{ reason: 'escalation', tier: 'emergent' }} />);
    expect(screen.queryByRole('button', { name: /reconnect|try again/i })).toBeNull();
  });

  it('falls back to a generic conversation-ended message for an unknown tier', () => {
    render(<EndOfConversationCard signal={{ reason: 'escalation' }} />);
    // The card still renders something useful — it does not crash on
    // a payload missing the optional `tier` field.
    expect(screen.getByRole('region', { name: /conversation ended/i })).toBeInTheDocument();
  });

  it('headlines the card with conversation vocabulary, not call vocabulary', () => {
    render(<EndOfConversationCard signal={{ reason: 'escalation', tier: 'emergent' }} />);
    expect(screen.getByText(/this conversation has ended/i)).toBeInTheDocument();
    // Regression anchor: the previous user-facing surface said "This
    // call has ended" — that wording must not regress.
    expect(screen.queryByText(/this call has ended/i)).toBeNull();
  });
});
