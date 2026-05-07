import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';

import { ClinicianSuggestions } from '@/components/clinician-suggestions';

const FIVE_RESULTS = {
  specialist_label: 'physiotherapist or occupational therapist',
  location_resolved: 'Brooklyn, Kings County, New York, United States',
  radius_km: 10,
  results: [
    {
      name: 'Park PT',
      address: '10 Main St, Brooklyn, 11215',
      phone: '+1 718-555-0100',
      url: 'https://www.openstreetmap.org/node/1',
      distance_km: 0.4,
    },
    {
      name: 'Bay Wellness',
      address: '20 Atlantic Ave, Brooklyn',
      phone: '+1 718-555-0200',
      url: 'https://www.openstreetmap.org/node/2',
      distance_km: 1.1,
    },
    {
      name: 'Atlantic Rehab',
      address: '30 Court St, Brooklyn',
      phone: '',
      url: 'https://www.openstreetmap.org/node/3',
      distance_km: 1.6,
    },
    {
      name: 'Greenpoint OT',
      address: '40 Manhattan Ave, Brooklyn',
      phone: '+1 718-555-0400',
      url: 'https://www.openstreetmap.org/way/4',
      distance_km: 2.4,
    },
    {
      name: 'Downtown Movement',
      address: '50 Boerum Pl, Brooklyn',
      phone: '+1 718-555-0500',
      url: 'https://www.openstreetmap.org/node/5',
      distance_km: 4.8,
    },
  ],
  count: 5,
};

const ZERO_RESULTS_ERROR =
  "I couldn't find any physiotherapist tagged in OpenStreetMap within 50 km of Brooklyn. " +
  "Your best bet is to search Google Maps for 'physiotherapist near Brooklyn' directly.";
const NETWORK_ERROR =
  "I couldn't reach the maps service just now. Try Google Maps for 'physiotherapist near Brooklyn' instead.";

describe('ClinicianSuggestions', () => {
  it('renders the in-flight state with a spinner and verbal-filler echo', () => {
    render(<ClinicianSuggestions result={null} />);
    expect(screen.getByTestId('clinician-suggestions')).toHaveAttribute('data-state', 'in-flight');
    expect(screen.getByText(/Searching around your area/i)).toBeInTheDocument();
  });

  it('renders five cards with the expected name, address, phone, distance, and OSM link', () => {
    render(<ClinicianSuggestions result={JSON.stringify(FIVE_RESULTS)} />);
    const cards = screen.getAllByTestId('clinician-card');
    expect(cards).toHaveLength(5);
    const first = cards[0];
    expect(within(first).getByText('Park PT')).toBeInTheDocument();
    expect(within(first).getByText('10 Main St, Brooklyn, 11215')).toBeInTheDocument();
    const phoneLink = within(first).getByRole('link', { name: '+1 718-555-0100' });
    expect(phoneLink).toHaveAttribute('href', 'tel:+1 718-555-0100');
    expect(within(first).getByText('0.4 km')).toBeInTheDocument();
    const osmLink = within(first).getByRole('link', { name: /view on OpenStreetMap/i });
    expect(osmLink).toHaveAttribute('href', 'https://www.openstreetmap.org/node/1');
    expect(osmLink).toHaveAttribute('target', '_blank');
  });

  it('omits the tel link when phone is empty rather than rendering an empty link', () => {
    render(<ClinicianSuggestions result={JSON.stringify(FIVE_RESULTS)} />);
    const atlantic = screen.getByText('Atlantic Rehab').closest('[data-testid="clinician-card"]');
    expect(atlantic).not.toBeNull();
    if (atlantic === null) return;
    const links = within(atlantic as HTMLElement).queryAllByRole('link');
    // Only the OSM link should be present on this card.
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute('href', expect.stringMatching(/openstreetmap\.org/));
  });

  it('renders a header reflecting specialist_label, location_resolved, and radius_km', () => {
    render(<ClinicianSuggestions result={JSON.stringify(FIVE_RESULTS)} />);
    const heading = screen.getByRole('heading', { level: 3 });
    expect(heading.textContent).toContain('physiotherapist or occupational therapist');
    expect(heading.textContent).toContain('Brooklyn, Kings County, New York, United States');
    expect(heading.textContent).toContain('within 10 km');
  });

  it('renders the zero-results error string verbatim with no card list', () => {
    render(<ClinicianSuggestions result={JSON.stringify({ error: ZERO_RESULTS_ERROR })} />);
    expect(screen.getByTestId('clinician-suggestions')).toHaveAttribute(
      'data-state',
      'zero-results',
    );
    expect(screen.getByText(ZERO_RESULTS_ERROR)).toBeInTheDocument();
    expect(screen.queryByTestId('clinician-card')).not.toBeInTheDocument();
  });

  it('renders the network-error string verbatim with no card list', () => {
    render(<ClinicianSuggestions result={JSON.stringify({ error: NETWORK_ERROR })} />);
    expect(screen.getByTestId('clinician-suggestions')).toHaveAttribute('data-state', 'error');
    expect(screen.getByText(NETWORK_ERROR)).toBeInTheDocument();
    expect(screen.queryByTestId('clinician-card')).not.toBeInTheDocument();
  });

  it('renders the OSM ODbL footer attribution in every state', () => {
    const states = [
      <ClinicianSuggestions key="in-flight" result={null} />,
      <ClinicianSuggestions key="success" result={JSON.stringify(FIVE_RESULTS)} />,
      <ClinicianSuggestions key="zero" result={JSON.stringify({ error: ZERO_RESULTS_ERROR })} />,
      <ClinicianSuggestions key="error" result={JSON.stringify({ error: NETWORK_ERROR })} />,
    ];
    for (const tree of states) {
      const { unmount } = render(tree);
      const attribution = screen.getByTestId('clinician-attribution');
      expect(attribution.textContent).toContain('OpenStreetMap contributors');
      const link = within(attribution).getByRole('link');
      expect(link).toHaveAttribute('href', 'https://www.openstreetmap.org/copyright');
      unmount();
    }
  });

  it('orders cards by distance ascending even if the payload is not pre-sorted', () => {
    const reordered = {
      ...FIVE_RESULTS,
      results: [...FIVE_RESULTS.results].reverse(),
    };
    render(<ClinicianSuggestions result={JSON.stringify(reordered)} />);
    const cards = screen.getAllByTestId('clinician-card');
    expect(cards[0].textContent).toContain('Park PT');
    expect(cards[cards.length - 1].textContent).toContain('Downtown Movement');
  });
});
