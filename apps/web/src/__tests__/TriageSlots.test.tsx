import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';

import { TriageSlots } from '@/components/triage-slots';
import { TRIAGE_SLOTS } from '@/lib/livekit-triage-state';

describe('TriageSlots', () => {
  it('renders one row per canonical OPQRST slot', () => {
    render(<TriageSlots slots={{}} />);
    for (const slot of TRIAGE_SLOTS) {
      expect(screen.getByTestId(`triage-slot-${slot.key}`)).toBeInTheDocument();
    }
  });

  it('shows the not-yet-disclosed placeholder for slots without a value', () => {
    render(<TriageSlots slots={{}} />);
    const locationRow = screen.getByTestId('triage-slot-location');
    expect(within(locationRow).getByText(/not yet disclosed/i)).toBeInTheDocument();
  });

  it('renders the value for a disclosed slot in place of the placeholder', () => {
    render(<TriageSlots slots={{ location: 'right wrist', onset: 'last week' }} />);
    const locationRow = screen.getByTestId('triage-slot-location');
    expect(within(locationRow).getByText('right wrist')).toBeInTheDocument();
    const onsetRow = screen.getByTestId('triage-slot-onset');
    expect(within(onsetRow).getByText('last week')).toBeInTheDocument();
    // Other slots remain placeholder.
    const qualityRow = screen.getByTestId('triage-slot-quality');
    expect(within(qualityRow).getByText(/not yet disclosed/i)).toBeInTheDocument();
  });

  it('updates when the slots prop changes', () => {
    const { rerender } = render(<TriageSlots slots={{}} />);
    expect(
      within(screen.getByTestId('triage-slot-severity')).getByText(/not yet disclosed/i),
    ).toBeInTheDocument();
    rerender(<TriageSlots slots={{ severity: 'moderate' }} />);
    expect(
      within(screen.getByTestId('triage-slot-severity')).getByText('moderate'),
    ).toBeInTheDocument();
  });
});
