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
  const setAttributes = vi.fn().mockResolvedValue(undefined);
  const Ctor = vi.fn().mockImplementation(() => {
    const handlers = new Map<string, (r: unknown) => Promise<void>>();
    return {
      connect,
      disconnect,
      on: vi.fn(),
      off: vi.fn(),
      once: vi.fn(),
      handlers,
      registerTextStreamHandler: (topic: string, handler: (r: unknown) => Promise<void>): void => {
        handlers.set(topic, handler);
      },
      unregisterTextStreamHandler: (topic: string): void => {
        handlers.delete(topic);
      },
      localParticipant: {
        identity: 'me',
        setMicrophoneEnabled: setMic,
        setAttributes,
      },
    };
  });
  return {
    connectMock: connect,
    disconnectMock: disconnect,
    setMicMock: setMic,
    RoomCtor: Ctor,
  };
});

// Stub the Supabase client surface the talk page reaches into when
// pushing the access token to LiveKit attributes.
vi.mock('@/lib/supabase', () => ({
  supabase: {
    auth: {
      getSession: vi.fn().mockResolvedValue({
        data: { session: { access_token: 'fake-jwt' } },
      }),
      onAuthStateChange: vi.fn().mockReturnValue({
        data: { subscription: { unsubscribe: vi.fn() } },
      }),
    },
  },
}));

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

  it('replaces the transcript with the end-of-conversation card when a session-end signal arrives', async () => {
    apiFetchMock.mockResolvedValue({
      token: 'lk-jwt-token',
      url: 'wss://test.livekit.cloud',
      room: 'user-123',
    });
    const user = userEvent.setup();
    renderWithProviders(<TalkPage />);

    await user.click(screen.getByRole('button', { name: /^connect$/i }));
    await screen.findByRole('button', { name: /^disconnect$/i });

    // Locate the active room instance the talk page mounted.
    const roomInstance = RoomCtor.mock.results[0]?.value as
      | { handlers?: Map<string, (r: unknown) => Promise<void>> }
      | undefined;
    // Drive the session-end topic emission through the registered
    // text-stream handler.
    const handler = roomInstance?.handlers?.get('lk.session-end');
    if (handler) {
      await handler({
        info: { topic: 'lk.session-end' },
        readAll: async () => JSON.stringify({ reason: 'escalation', tier: 'emergent' }),
      });
    }

    await waitFor(() => {
      expect(screen.getByText(/call your local emergency number now/i)).toBeInTheDocument();
    });
    // No Reconnect / Try-again button while the end-of-conversation card is showing.
    expect(screen.queryByRole('button', { name: /reconnect|try again/i })).toBeNull();
    // No Connect / Disconnect / Mic affordances either — per the AC,
    // there must be no way to nudge the user back into the voice loop
    // once the safety screen has routed them away.
    expect(screen.queryByRole('button', { name: /^connect$/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /^disconnect$/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /microphone/i })).toBeNull();
    // And no transcript surface — the card replaces it entirely.
    expect(screen.queryByText(/transcript/i)).toBeNull();
  });

  it('does NOT proactively disconnect after a session-end signal — the script must finish playing', async () => {
    // Regression: a previous implementation set a 500ms timer that
    // called `room.disconnect()` on the assumption that the script
    // audio would have played by then. But the agent emits the
    // session-end signal BEFORE speaking, so the audio is still
    // arriving when the timer fires; the early disconnect cuts the
    // WebRTC track and the user hears nothing. The server is the
    // authoritative teardown via room.delete (after the script
    // finishes plus a 500ms drain) — the frontend just renders the
    // card and waits for the natural disconnect.
    apiFetchMock.mockResolvedValue({
      token: 'lk-jwt-token',
      url: 'wss://test.livekit.cloud',
      room: 'user-123',
    });
    const user = userEvent.setup();
    renderWithProviders(<TalkPage />);

    await user.click(screen.getByRole('button', { name: /^connect$/i }));
    await screen.findByRole('button', { name: /^disconnect$/i });

    const roomInstance = RoomCtor.mock.results[0]?.value as
      | { handlers?: Map<string, (r: unknown) => Promise<void>> }
      | undefined;
    const handler = roomInstance?.handlers?.get('lk.session-end');
    if (handler) {
      await handler({
        info: { topic: 'lk.session-end' },
        readAll: async () => JSON.stringify({ reason: 'escalation', tier: 'emergent' }),
      });
    }

    await screen.findByText(/call your local emergency number now/i);
    // Wait well past the old 500ms timer to confirm we never disconnect.
    await new Promise((resolve) => setTimeout(resolve, 800));
    expect(disconnectMock).not.toHaveBeenCalled();
  });
});
