import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const { apiFetchMock } = vi.hoisted(() => ({
  apiFetchMock: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  apiFetch: apiFetchMock,
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, msg: string) {
      super(msg);
      this.status = status;
    }
  },
}));

vi.mock('@tanstack/react-router', () => ({
  Link: ({ children }: { children: React.ReactNode }) => <a>{children}</a>,
  createFileRoute: () => () => ({}),
  redirect: () => null,
  useParams: () => ({ id: 'conv-1' }),
}));

import { ConversationView } from '@/routes/history.$id';

function renderWithProviders(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe('ConversationView', () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it('renders user, assistant, and tool messages with role styling', async () => {
    apiFetchMock.mockResolvedValue({
      id: 'conv-1',
      started_at: '2026-05-04T12:00:00+00:00',
      ended_at: '2026-05-04T12:05:00+00:00',
      summary: 'Talked about the weather',
      metadata: {},
      messages: [
        {
          id: 'm1',
          role: 'user',
          content: 'what is the weather in Berlin?',
          tool_name: null,
          tool_args: null,
          tool_result: null,
          created_at: '2026-05-04T12:00:01+00:00',
        },
        {
          id: 'm2',
          role: 'tool',
          content: '',
          tool_name: 'get_weather',
          tool_args: { city: 'Berlin' },
          tool_result: 'It is 20 degrees.',
          created_at: '2026-05-04T12:00:02+00:00',
        },
        {
          id: 'm3',
          role: 'assistant',
          content: 'It is 20 degrees in Berlin.',
          tool_name: null,
          tool_args: null,
          tool_result: null,
          created_at: '2026-05-04T12:00:03+00:00',
        },
      ],
    });
    renderWithProviders(<ConversationView id="conv-1" />);

    await waitFor(() => {
      expect(screen.getByText('what is the weather in Berlin?')).toBeInTheDocument();
    });
    expect(screen.getByText('It is 20 degrees in Berlin.')).toBeInTheDocument();
    expect(screen.getByText('get_weather')).toBeInTheDocument();
    expect(screen.getByText('It is 20 degrees.')).toBeInTheDocument();
    expect(screen.getByText('Talked about the weather')).toBeInTheDocument();

    // Role-styled bubbles: user vs assistant get distinct styling. We
    // assert via the data-role attribute the component places on each
    // bubble — testing the literal class names would couple the test
    // to implementation details.
    const userBubble = screen.getByText('what is the weather in Berlin?').closest('li');
    const assistantBubble = screen.getByText('It is 20 degrees in Berlin.').closest('li');
    expect(userBubble?.getAttribute('data-role')).toBe('user');
    expect(assistantBubble?.getAttribute('data-role')).toBe('assistant');
  });

  it('shows a not-found message when the API returns 404', async () => {
    const ApiErrorClass = (await import('@/lib/api')).ApiError as unknown as new (
      status: number,
      msg: string,
    ) => Error;
    apiFetchMock.mockRejectedValue(new ApiErrorClass(404, 'not found'));
    renderWithProviders(<ConversationView id="conv-1" />);
    await waitFor(() => {
      expect(screen.getByText(/conversation not found/i)).toBeInTheDocument();
    });
  });

  it('shows a generic error for non-404 failures', async () => {
    apiFetchMock.mockRejectedValue(new Error('network down'));
    renderWithProviders(<ConversationView id="conv-1" />);
    await waitFor(() => {
      expect(screen.getByText(/couldn't load the conversation/i)).toBeInTheDocument();
    });
  });
});
