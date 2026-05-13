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
  LimberHome,
} from '@/components/home';

function renderWithProviders(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe('LimberHome', () => {
  it('renders the limber wordmark in the app header', () => {
    renderWithProviders(<LimberHome />);
    // The wordmark is the lowercase "limber." word with its orange
    // period — read as an aria-labelled span by assistive tech.
    expect(screen.getAllByLabelText(/limber/i).length).toBeGreaterThan(0);
  });

  it('exposes Talk and History navigation', () => {
    renderWithProviders(<LimberHome />);
    // The router's <Link> mock renders an `<a>` without `href`, which
    // strips the implicit `link` role per the ARIA spec — assert via
    // visible text instead so the test is robust to that mock detail.
    expect(screen.getByText(/^Talk$/)).toBeInTheDocument();
    expect(screen.getByText(/^History$/)).toBeInTheDocument();
  });

  it('exposes a sign-out affordance in the header', () => {
    renderWithProviders(<LimberHome />);
    expect(screen.getByRole('button', { name: /sign out/i })).toBeInTheDocument();
  });

  it('renders the talk-page slot (start-talking affordance)', () => {
    renderWithProviders(<LimberHome />);
    expect(screen.getByRole('button', { name: /start talking/i })).toBeInTheDocument();
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
