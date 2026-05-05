import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// `TalkPage` transitively imports the LiveKit client; stub it so this
// test focuses on the disclaimer + scope structure rather than the
// WebRTC ceremony exercised in `TalkPage.test.tsx`.
vi.mock('@/components/talk-page', () => ({
  TalkPage: () => (
    <button type="button" aria-label="Connect">
      Connect
    </button>
  ),
}));

vi.mock('@/lib/supabase', () => ({
  supabase: {
    auth: {
      signOut: vi.fn().mockResolvedValue({ error: null }),
    },
  },
}));

vi.mock('@tanstack/react-router', () => ({
  Link: ({ children, ...rest }: { children: React.ReactNode }) => (
    <a {...(rest as Record<string, unknown>)}>{children}</a>
  ),
  useNavigate: () => vi.fn(),
}));

import {
  DisclaimerBanner,
  IN_SCOPE_CONDITIONS,
  ScopeStatement,
  TriageHome,
} from '@/components/triage-home';

function renderWithProviders(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe('TriageHome', () => {
  it('renders the educational-tool disclaimer banner', () => {
    renderWithProviders(<TriageHome />);
    const disclaimer = screen.getByRole('region', { name: /educational tool disclaimer/i });
    expect(disclaimer).toBeInTheDocument();
    expect(disclaimer).toHaveTextContent(/educational tool, not a doctor/i);
    expect(disclaimer).toHaveTextContent(/not a substitute/i);
  });

  it('lists the five in-scope conditions in the scope statement', () => {
    renderWithProviders(<TriageHome />);
    const scope = screen.getByRole('region', { name: /what this tool can help with/i });
    expect(scope).toHaveTextContent(/carpal tunnel/i);
    expect(scope).toHaveTextContent(/computer vision syndrome/i);
    expect(scope).toHaveTextContent(/tension-type headache/i);
    expect(scope).toHaveTextContent(/text neck|trapezius/i);
    expect(scope).toHaveTextContent(/lumbar/i);
  });

  it('renders the talk-button affordance', () => {
    renderWithProviders(<TriageHome />);
    expect(screen.getByRole('button', { name: /connect/i })).toBeInTheDocument();
  });

  it('does not render the memory sidebar', () => {
    renderWithProviders(<TriageHome />);
    // The template's memory sidebar advertises a "what I remember about
    // you" panel; ensuring that copy is absent is a regression check
    // that the sidebar is not silently re-introduced.
    expect(screen.queryByText(/i'll remember things you tell me here/i)).toBeNull();
  });
});

describe('DisclaimerBanner', () => {
  it('renders standalone with the same load-bearing copy', () => {
    renderWithProviders(<DisclaimerBanner />);
    expect(screen.getByText(/educational tool, not a doctor/i)).toBeInTheDocument();
  });
});

describe('ScopeStatement', () => {
  it('renders one list item per in-scope condition', () => {
    renderWithProviders(<ScopeStatement />);
    expect(IN_SCOPE_CONDITIONS).toHaveLength(5);
    for (const condition of IN_SCOPE_CONDITIONS) {
      expect(screen.getByText(condition)).toBeInTheDocument();
    }
  });
});
