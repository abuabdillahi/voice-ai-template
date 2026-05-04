import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// `livekit-client` opens a websocket as soon as `Room.connect` is
// invoked, which happy-dom does not implement. We mock the surface
// the talk page actually uses; the rest of the API stays as the real
// module so type exports keep working.
const { connectMock, disconnectMock, setMicMock, RoomCtor } = vi.hoisted(() => {
  const connect = vi.fn().mockResolvedValue(undefined);
  const disconnect = vi.fn().mockResolvedValue(undefined);
  const setMic = vi.fn().mockResolvedValue(undefined);
  const Ctor = vi.fn().mockImplementation(() => ({
    connect,
    disconnect,
    on: vi.fn(),
    off: vi.fn(),
    localParticipant: {
      identity: 'me',
      setMicrophoneEnabled: setMic,
    },
  }));
  return { connectMock: connect, disconnectMock: disconnect, setMicMock: setMic, RoomCtor: Ctor };
});

vi.mock('livekit-client', async () => {
  const actual = await vi.importActual<typeof import('livekit-client')>('livekit-client');
  return {
    ...actual,
    Room: RoomCtor,
  };
});

// `apiFetch` would otherwise hit the real backend. The test asserts
// the mutation is wired correctly, not the network shape.
const { apiFetchMock } = vi.hoisted(() => ({
  apiFetchMock: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  apiFetch: apiFetchMock,
  ApiError: class ApiError extends Error {},
}));

import { TalkPage } from '@/components/talk-page';

function renderWithProviders(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe('TalkPage', () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
    connectMock.mockClear();
    disconnectMock.mockClear();
    setMicMock.mockClear();
    RoomCtor.mockClear();
  });

  it('renders the connect button by default', () => {
    renderWithProviders(<TalkPage />);
    expect(screen.getByRole('button', { name: /^connect$/i })).toBeInTheDocument();
    expect(screen.getByText(/no transcript yet/i)).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent(/idle/i);
  });

  it('fetches a token and connects to the room when Connect is clicked', async () => {
    apiFetchMock.mockResolvedValue({
      token: 'lk-jwt-token',
      url: 'wss://test.livekit.cloud',
      room: 'user-123',
    });
    const user = userEvent.setup();
    renderWithProviders(<TalkPage />);

    await user.click(screen.getByRole('button', { name: /^connect$/i }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith('/livekit/token', {
        method: 'POST',
        body: {},
      });
    });
    expect(connectMock).toHaveBeenCalledWith('wss://test.livekit.cloud', 'lk-jwt-token');
    // The disconnect button replaces connect once the mutation
    // resolves and state flips to "connected".
    await screen.findByRole('button', { name: /^disconnect$/i });
  });

  it('mic toggle is disabled until a connection is established', () => {
    renderWithProviders(<TalkPage />);
    expect(screen.getByRole('button', { name: /unmute microphone/i })).toBeDisabled();
  });

  it('shows an error message when token fetch fails', async () => {
    apiFetchMock.mockRejectedValue(new Error('network down'));
    const user = userEvent.setup();
    renderWithProviders(<TalkPage />);

    await user.click(screen.getByRole('button', { name: /^connect$/i }));
    expect(await screen.findByText(/network down/i)).toBeInTheDocument();
    expect(connectMock).not.toHaveBeenCalled();
  });
});
