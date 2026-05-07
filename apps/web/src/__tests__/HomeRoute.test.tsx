import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// `TalkPage` transitively imports the LiveKit client and owns the
// pre-connect disclaimer/scope/start-talking hero in the redesigned
// layout. The home shell test stubs it to a placeholder so we can
// focus on the chrome (header + nav + sign-out + talk-page slot)
// without re-asserting the talk-page internals — those have their own
// suite.
vi.mock('@/components/talk-page', () => ({
  TalkPage: () => (
    <button type="button" aria-label="Start talking">
      Start talking
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
  SarjyHome,
} from '@/components/sarjy-home';

function renderWithProviders(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe('SarjyHome', () => {
  it('renders the Sarjy wordmark in the app header', () => {
    renderWithProviders(<SarjyHome />);
    // The wordmark is the "Sarjy" text adjacent to the equalizer logo
    // SVG in the AppHeader. The redesign drops the standalone <h1>
    // because the wordmark is brand-mark-shaped.
    expect(screen.getAllByLabelText(/sarjy/i).length).toBeGreaterThan(0);
  });

  it('exposes Talk and History navigation', () => {
    renderWithProviders(<SarjyHome />);
    // The router's <Link> mock renders an `<a>` without `href`, which
    // strips the implicit `link` role per the ARIA spec — assert via
    // visible text instead so the test is robust to that mock detail.
    expect(screen.getByText(/^Talk$/)).toBeInTheDocument();
    expect(screen.getByText(/^History$/)).toBeInTheDocument();
  });

  it('exposes a sign-out affordance in the header', () => {
    renderWithProviders(<SarjyHome />);
    expect(screen.getByRole('button', { name: /sign out/i })).toBeInTheDocument();
  });

  it('renders the talk-page slot (start-talking affordance)', () => {
    renderWithProviders(<SarjyHome />);
    expect(screen.getByRole('button', { name: /start talking/i })).toBeInTheDocument();
  });

  it('does not render the memory sidebar', () => {
    renderWithProviders(<SarjyHome />);
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
