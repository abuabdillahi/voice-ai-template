import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// `apiFetch` is mocked at the module boundary so the component test
// does not depend on a running API. The mock reference is hoisted so
// the factory closure resolves correctly regardless of import order.
const { apiFetchMock } = vi.hoisted(() => ({
  apiFetchMock: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  apiFetch: apiFetchMock,
  ApiError: class ApiError extends Error {},
}));

import { MemorySidebar } from '@/components/memory-sidebar';

function renderWithProviders(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

/**
 * The sidebar fans out to two endpoints (preferences + recent memories).
 * Tests dispatch on the URL string so each panel can be exercised
 * independently without coupling assertions to call order.
 */
function routeApiFetch(routes: Record<string, unknown>) {
  apiFetchMock.mockImplementation((path: string) => {
    if (path in routes) {
      const value = routes[path];
      if (value instanceof Error) return Promise.reject(value);
      return Promise.resolve(value);
    }
    return Promise.reject(new Error(`unexpected path ${path}`));
  });
}

describe('MemorySidebar', () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it('shows the empty-state hint when no preferences are saved', async () => {
    routeApiFetch({
      '/preferences': { preferences: {} },
      '/memories/recent': { memories: [] },
    });
    renderWithProviders(<MemorySidebar />);

    await waitFor(() => {
      expect(screen.getByText(/i'll remember things you tell me here/i)).toBeInTheDocument();
    });
    expect(apiFetchMock).toHaveBeenCalledWith('/preferences');
  });

  it('renders each preference as a labelled row', async () => {
    routeApiFetch({
      '/preferences': {
        preferences: {
          favorite_color: 'blue',
          preferred_name: 'Alice',
        },
      },
      '/memories/recent': { memories: [] },
    });
    renderWithProviders(<MemorySidebar />);

    await waitFor(() => {
      expect(screen.getByText('favorite_color')).toBeInTheDocument();
    });
    expect(screen.getByText('blue')).toBeInTheDocument();
    expect(screen.getByText('preferred_name')).toBeInTheDocument();
    expect(screen.getByText('Alice')).toBeInTheDocument();
  });

  it('shows an error message when the preferences fetch fails', async () => {
    routeApiFetch({
      '/preferences': new Error('network down'),
      '/memories/recent': { memories: [] },
    });
    renderWithProviders(<MemorySidebar />);

    await waitFor(() => {
      expect(screen.getByText(/couldn't load preferences/i)).toBeInTheDocument();
    });
  });

  it('shows the empty-state hint for the recent-memories section', async () => {
    routeApiFetch({
      '/preferences': { preferences: {} },
      '/memories/recent': { memories: [] },
    });
    renderWithProviders(<MemorySidebar />);

    await waitFor(() => {
      expect(
        screen.getByText(/things you mention in conversation will appear here/i),
      ).toBeInTheDocument();
    });
    // The recent-memories endpoint is fetched on the same render so
    // the polling cadence aligns with the preferences card.
    expect(apiFetchMock).toHaveBeenCalledWith('/memories/recent');
  });

  it('renders each recent memory in a list', async () => {
    routeApiFetch({
      '/preferences': { preferences: {} },
      '/memories/recent': {
        memories: [
          { id: 'm1', content: 'is learning Spanish' },
          { id: 'm2', content: 'has a daughter named Maya' },
        ],
      },
    });
    renderWithProviders(<MemorySidebar />);

    await waitFor(() => {
      expect(screen.getByText(/is learning spanish/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/has a daughter named maya/i)).toBeInTheDocument();
  });

  it('shows an error message when the memories fetch fails', async () => {
    routeApiFetch({
      '/preferences': { preferences: {} },
      '/memories/recent': new Error('mem0 unavailable'),
    });
    renderWithProviders(<MemorySidebar />);

    await waitFor(() => {
      expect(screen.getByText(/couldn't load memories/i)).toBeInTheDocument();
    });
  });
});
