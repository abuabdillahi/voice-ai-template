import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { EndOfCallCard } from '@/components/end-of-call-card';

describe('EndOfCallCard', () => {
  it('renders the tier-1 emergency routing copy', () => {
    render(<EndOfCallCard signal={{ reason: 'escalation', tier: 'emergent' }} />);
    expect(screen.getByText(/call your local emergency number now/i)).toBeInTheDocument();
  });

  it('renders the tier-2 urgent-care routing copy', () => {
    render(<EndOfCallCard signal={{ reason: 'escalation', tier: 'urgent' }} />);
    expect(screen.getByText(/please seek urgent care today/i)).toBeInTheDocument();
  });

  it('does NOT render a Reconnect button', () => {
    render(<EndOfCallCard signal={{ reason: 'escalation', tier: 'emergent' }} />);
    expect(screen.queryByRole('button', { name: /reconnect|try again/i })).toBeNull();
  });

  it('falls back to a generic ended-call message for an unknown tier', () => {
    render(<EndOfCallCard signal={{ reason: 'escalation' }} />);
    // The card still renders something useful — it does not crash on
    // a payload missing the optional `tier` field.
    expect(screen.getByRole('region', { name: /call ended/i })).toBeInTheDocument();
  });
});
