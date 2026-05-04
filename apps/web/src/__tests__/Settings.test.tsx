import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const { signOutMock, apiFetchMock } = vi.hoisted(() => ({
  signOutMock: vi.fn(),
  apiFetchMock: vi.fn(),
}));

vi.mock('@/lib/supabase', () => ({
  supabase: {
    auth: {
      signOut: signOutMock,
    },
  },
}));

vi.mock('@/lib/api', () => ({
  apiFetch: apiFetchMock,
  ApiError: class ApiError extends Error {},
}));

import { SettingsForm } from '@/components/settings-form';

function renderForm(props: Parameters<typeof SettingsForm>[0] = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <SettingsForm {...props} />
    </QueryClientProvider>,
  );
}

describe('SettingsForm', () => {
  beforeEach(() => {
    signOutMock.mockReset();
    apiFetchMock.mockReset();
    apiFetchMock.mockResolvedValue({ preferences: {} });
  });

  it('renders preferred name + voice selector + sign-out', async () => {
    renderForm();
    await waitFor(() => {
      expect(screen.getByLabelText(/preferred name/i)).toBeInTheDocument();
    });
    expect(screen.getByLabelText(/voice/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /save/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /sign out/i })).toBeInTheDocument();
  });

  it('seeds the name field from GET /preferences', async () => {
    apiFetchMock.mockResolvedValue({
      preferences: { preferred_name: 'Alice', voice: 'sage' },
    });
    renderForm();
    await waitFor(() => {
      expect(screen.getByLabelText(/preferred name/i)).toHaveValue('Alice');
    });
  });

  it('rejects names longer than 80 chars at the client', async () => {
    const user = userEvent.setup();
    renderForm();
    // Wait until the input is enabled — until the initial GET resolves
    // the field is `disabled`, and userEvent.type does not deliver
    // events to disabled inputs.
    const input = (await screen.findByLabelText(/preferred name/i)) as HTMLInputElement;
    await waitFor(() => expect(input).not.toBeDisabled());
    await user.type(input, 'x'.repeat(81));
    await user.click(screen.getByRole('button', { name: /save/i }));
    await waitFor(() => {
      expect(screen.getByText(/80 characters or fewer/i)).toBeInTheDocument();
    });
    // Only the initial GET should have run; no PUTs.
    expect(
      apiFetchMock.mock.calls.filter(([, opts]) => opts && opts.method === 'PUT'),
    ).toHaveLength(0);
  });

  it('issues PUT only for changed fields', async () => {
    apiFetchMock.mockResolvedValue({
      preferences: { preferred_name: 'Alice' },
    });
    const user = userEvent.setup();
    renderForm();
    await waitFor(() => {
      expect(screen.getByLabelText(/preferred name/i)).toHaveValue('Alice');
    });
    const nameInput = screen.getByLabelText(/preferred name/i);
    await user.clear(nameInput);
    await user.type(nameInput, 'Sam');
    await user.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() => {
      expect(
        apiFetchMock.mock.calls.some(
          ([path, opts]) =>
            path === '/preferences/preferred_name' &&
            opts &&
            opts.method === 'PUT' &&
            opts.body &&
            (opts.body as { value: string }).value === 'Sam',
        ),
      ).toBe(true);
    });
    // No voice PUT — voice was untouched.
    expect(
      apiFetchMock.mock.calls.some(
        ([path, opts]) => path === '/preferences/voice' && opts && opts.method === 'PUT',
      ),
    ).toBe(false);
  });

  it('signs the user out and notifies the parent', async () => {
    signOutMock.mockResolvedValue({ error: null });
    const onSignedOut = vi.fn();
    const user = userEvent.setup();
    renderForm({ onSignedOut });

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /sign out/i })).toBeInTheDocument();
    });
    await user.click(screen.getByRole('button', { name: /sign out/i }));

    await waitFor(() => {
      expect(signOutMock).toHaveBeenCalled();
    });
    expect(onSignedOut).toHaveBeenCalled();
  });
});
