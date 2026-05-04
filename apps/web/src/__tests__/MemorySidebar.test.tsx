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

describe('MemorySidebar', () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it('shows the empty-state hint when no preferences are saved', async () => {
    apiFetchMock.mockResolvedValue({ preferences: {} });
    renderWithProviders(<MemorySidebar />);

    await waitFor(() => {
      expect(screen.getByText(/i'll remember things you tell me here/i)).toBeInTheDocument();
    });
    expect(apiFetchMock).toHaveBeenCalledWith('/preferences');
  });

  it('renders each preference as a labelled row', async () => {
    apiFetchMock.mockResolvedValue({
      preferences: {
        favorite_color: 'blue',
        preferred_name: 'Alice',
      },
    });
    renderWithProviders(<MemorySidebar />);

    await waitFor(() => {
      expect(screen.getByText('favorite_color')).toBeInTheDocument();
    });
    expect(screen.getByText('blue')).toBeInTheDocument();
    expect(screen.getByText('preferred_name')).toBeInTheDocument();
    expect(screen.getByText('Alice')).toBeInTheDocument();
  });

  it('shows an error message when the fetch fails', async () => {
    apiFetchMock.mockRejectedValue(new Error('network down'));
    renderWithProviders(<MemorySidebar />);

    await waitFor(() => {
      expect(screen.getByText(/couldn't load preferences/i)).toBeInTheDocument();
    });
  });
});
