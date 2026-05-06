import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const { apiFetchMock } = vi.hoisted(() => ({
  apiFetchMock: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  apiFetch: apiFetchMock,
  ApiError: class ApiError extends Error {},
}));

// `Link` from TanStack Router is mocked so the component renders
// without a Router context. Tests assert against the rendered text +
// destination, not the underlying navigation behaviour (covered by
// TanStack's own suite).
vi.mock('@tanstack/react-router', () => ({
  Link: ({
    children,
    to,
    params,
  }: {
    children: React.ReactNode;
    to: string;
    params?: Record<string, string>;
  }) => (
    <a data-to={to} data-params={params ? JSON.stringify(params) : undefined}>
      {children}
    </a>
  ),
  createFileRoute: () => () => ({}),
  redirect: () => null,
}));

import { HistoryList } from '@/routes/history.index';

function renderWithProviders(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe('HistoryList', () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it('shows the empty state when no conversations exist', async () => {
    apiFetchMock.mockResolvedValue({ conversations: [] });
    renderWithProviders(<HistoryList />);
    await waitFor(() => {
      expect(screen.getByText(/no conversations yet/i)).toBeInTheDocument();
    });
    expect(apiFetchMock).toHaveBeenCalledWith('/conversations');
  });

  it('renders one row per conversation with summary and message count', async () => {
    apiFetchMock.mockResolvedValue({
      conversations: [
        {
          id: 'aaa',
          started_at: '2026-05-04T12:00:00+00:00',
          ended_at: '2026-05-04T12:05:00+00:00',
          summary: 'Talked about the weather',
          message_count: 5,
        },
        {
          id: 'bbb',
          started_at: '2026-05-03T10:00:00+00:00',
          ended_at: null,
          summary: null,
          message_count: 0,
        },
      ],
    });
    renderWithProviders(<HistoryList />);
    await waitFor(() => {
      expect(screen.getByText('Talked about the weather')).toBeInTheDocument();
    });
    expect(screen.getByText(/5 messages/i)).toBeInTheDocument();
    expect(screen.getByText(/no summary yet/i)).toBeInTheDocument();
    expect(screen.getByText(/0 messages/i)).toBeInTheDocument();
  });

  it('shows an error message when the fetch fails', async () => {
    apiFetchMock.mockRejectedValue(new Error('network down'));
    renderWithProviders(<HistoryList />);
    await waitFor(() => {
      expect(screen.getByText(/couldn't load your conversations/i)).toBeInTheDocument();
    });
  });
});
