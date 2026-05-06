/**
 * Route-level test for the history list / detail relationship.
 *
 * The component-only tests in `HistoryList.test.tsx` and
 * `ConversationView.test.tsx` cannot catch the missing-Outlet failure
 * mode that issue 16 fixes — that bug only surfaces once both routes
 * are mounted in the same router and we navigate from one to the
 * other. This file mounts the real generated `routeTree` against an
 * in-memory history so that any future regression in the parent/child
 * nesting (e.g. someone renaming back to `history.$id.tsx` and
 * forgetting the `<Outlet />`) shows up here.
 */

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider, createMemoryHistory, createRouter } from '@tanstack/react-router';

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

vi.mock('@/lib/supabase', () => ({
  supabase: {
    auth: {
      getSession: () => Promise.resolve({ data: { session: { user: { id: 'u' } } } }),
    },
  },
}));

import { routeTree } from '@/routeTree.gen';

function renderAt(initialPath: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [initialPath] }),
    context: { queryClient },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

describe('history routes', () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it('mounts ConversationView at /history/$id', async () => {
    apiFetchMock.mockResolvedValueOnce({
      id: 'conv-1',
      started_at: '2026-05-04T12:00:00+00:00',
      ended_at: '2026-05-04T12:05:00+00:00',
      summary: 'Talked about the weather',
      metadata: {},
      messages: [
        {
          id: 'm1',
          role: 'user',
          content: 'unique-detail-marker-123',
          tool_name: null,
          tool_args: null,
          tool_result: null,
          created_at: '2026-05-04T12:00:01+00:00',
        },
      ],
    });

    renderAt('/history/conv-1');

    await waitFor(() => {
      expect(screen.getByText('unique-detail-marker-123')).toBeInTheDocument();
    });
  });
});
