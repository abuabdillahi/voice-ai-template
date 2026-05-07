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

// `useNavigate` is invoked by the talk page when handing off to the
// dedicated /session-end route after the WebRTC teardown completes.
// The test exposes the spy so individual cases can assert on the
// navigation target without standing up a Router context.
const { navigateMock } = vi.hoisted(() => ({ navigateMock: vi.fn() }));

vi.mock('@tanstack/react-router', () => ({
  useNavigate: () => navigateMock,
  Link: ({ children, ...rest }: { children: React.ReactNode }) => (
    <a {...(rest as Record<string, unknown>)}>{children}</a>
  ),
  createFileRoute: () => () => ({}),
  redirect: () => null,
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

// The redesigned pre-connect flow does a `getUserMedia` mic-permission
// preflight before opening the LiveKit transport so a denied prompt
// fails fast. happy-dom does not implement `MediaDevices`, so stub
// the surface for tests that drive the start flow successfully.
beforeEach(() => {
  Object.defineProperty(globalThis.navigator, 'mediaDevices', {
    configurable: true,
    value: {
      getUserMedia: vi.fn().mockResolvedValue({
        getTracks: () => [{ stop: vi.fn() }],
      }),
    },
  });
});

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
    // Default implementation routes by path so both the
    // pre-connect `/sessions/prior-status` query and the start-flow
    // `/livekit/token` mutation resolve with sensible shapes. Tests
    // that need a different prior-status or a token failure can call
    // `apiFetchMock.mockImplementation` (or `mockRejectedValue`) again
    // to override.
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/sessions/prior-status') return { is_returning_user: false };
      if (path === '/livekit/token') {
        return {
          token: 'lk-jwt-token',
          url: 'wss://test.livekit.cloud',
          room: 'user-123',
        };
      }
      return undefined;
    });
    connectMock.mockClear();
    disconnectMock.mockClear();
    setMicMock.mockClear();
    RoomCtor.mockClear();
    navigateMock.mockClear();
    sessionStorage.clear();
  });

  it('renders the start-talking CTA in the pre-connect view', () => {
    renderWithProviders(<TalkPage />);
    // The redesigned pre-connect surface fuses Connect + Unmute into a
    // single "Start talking" affordance. The aria-label is the literal
    // verb the user sees.
    expect(screen.getByRole('button', { name: /start talking/i })).toBeInTheDocument();
  });

  it('shows the permanent first-time disclaimer when the user has no prior sessions', async () => {
    // Default mockImplementation already returns `is_returning_user: false`.
    renderWithProviders(<TalkPage />);
    // First-time card surfaces the full amber disclaimer (the agent
    // plays the matching long opener over audio at the same time) and
    // exposes no collapse affordance — the safety scope stays
    // permanently visible until the user has heard it once.
    const region = await screen.findByRole('region', { name: /educational tool disclaimer/i });
    expect(region).toHaveTextContent(/educational tool, not a doctor/i);
    expect(region).toHaveTextContent(/call your local emergency number now/i);
    expect(region.querySelector('button')).toBeNull();
  });

  it('shows the collapsed safety pill when the user is a returning visitor', async () => {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/sessions/prior-status') return { is_returning_user: true };
      if (path === '/livekit/token') {
        return {
          token: 'lk-jwt-token',
          url: 'wss://test.livekit.cloud',
          room: 'user-123',
        };
      }
      return undefined;
    });
    renderWithProviders(<TalkPage />);
    // Returning users see the collapsed pill with the original
    // "Educational tool, not a doctor." one-liner and a chevron
    // affordance — the body is no longer load-bearing on subsequent
    // sessions, so the full amber card collapses behind the toggle.
    const toggle = await screen.findByRole('button', { name: /safety scope/i });
    expect(toggle).toHaveTextContent(/educational tool, not a doctor/i);
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
  });

  it('fetches a token and connects (with mic auto-enabled) when Start talking is clicked', async () => {
    apiFetchMock.mockResolvedValue({
      token: 'lk-jwt-token',
      url: 'wss://test.livekit.cloud',
      room: 'user-123',
    });
    const user = userEvent.setup();
    renderWithProviders(<TalkPage />);

    await user.click(screen.getByRole('button', { name: /start talking/i }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith('/livekit/token', {
        method: 'POST',
        body: {},
      });
    });
    expect(connectMock).toHaveBeenCalledWith('wss://test.livekit.cloud', 'lk-jwt-token');
    // Auto-unmute on connect: the redesign drops the second-click
    // friction tax so the user only has to make one decision. The
    // talk-page contract is therefore "after connect, mic is enabled".
    await waitFor(() => {
      expect(setMicMock).toHaveBeenCalledWith(true);
    });
    // The mute-toggle button should now be visible in the in-session
    // controls bar.
    await screen.findByRole('button', { name: /mute microphone/i });
  });

  it('shows an error message when token fetch fails', async () => {
    apiFetchMock.mockRejectedValue(new Error('network down'));
    const user = userEvent.setup();
    renderWithProviders(<TalkPage />);

    await user.click(screen.getByRole('button', { name: /start talking/i }));
    expect(await screen.findByText(/network down/i)).toBeInTheDocument();
    expect(connectMock).not.toHaveBeenCalled();
  });

  it('surfaces a friendly mic-permission error when getUserMedia is denied', async () => {
    const denied = Object.assign(new Error('denied'), { name: 'NotAllowedError' });
    Object.defineProperty(globalThis.navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn().mockRejectedValue(denied) },
    });
    apiFetchMock.mockResolvedValue({
      token: 'lk-jwt-token',
      url: 'wss://test.livekit.cloud',
      room: 'user-123',
    });
    const user = userEvent.setup();
    renderWithProviders(<TalkPage />);

    await user.click(screen.getByRole('button', { name: /start talking/i }));
    expect(await screen.findByText(/microphone permission denied/i)).toBeInTheDocument();
    // No LiveKit transport should be opened when the preflight fails.
    expect(connectMock).not.toHaveBeenCalled();
  });

  it('hands off to /session-end on escalation, with the tier preserved in the stash', async () => {
    apiFetchMock.mockResolvedValue({
      token: 'lk-jwt-token',
      url: 'wss://test.livekit.cloud',
      room: 'user-123',
    });
    const user = userEvent.setup();
    renderWithProviders(<TalkPage />);

    await user.click(screen.getByRole('button', { name: /start talking/i }));
    await screen.findByRole('button', { name: /mute microphone/i });

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

    // The talk page hands escalation off to the same /session-end
    // route as user-ended sessions, preserving the tier in the stash
    // so the summary surface can render the right routing copy.
    await waitFor(() => {
      expect(navigateMock).toHaveBeenCalledWith({ to: '/session-end' });
    });
    const stash = sessionStorage.getItem('sarjy.session-summary.v1');
    expect(stash).toBeTruthy();
    const parsed = JSON.parse(stash!) as { signal: { reason: string; tier?: string } };
    expect(parsed.signal.reason).toBe('escalation');
    expect(parsed.signal.tier).toBe('emergent');

    // While the navigation is pending, the talk page renders the same
    // summary surface inline so the user sees the routing copy while
    // the agent's escalation script is still draining over the live
    // WebRTC connection. No way back into the voice loop is exposed —
    // once the safety screen has routed the user away, the only
    // egress is the page chrome.
    expect(screen.getByText(/call your local emergency number now/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /reconnect|try again/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /^start talking$/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /microphone/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /end session/i })).toBeNull();
    expect(screen.getByRole('region', { name: /transcript/i })).toBeInTheDocument();
  });

  it('hands off to /session-end after the user clicks End session', async () => {
    apiFetchMock.mockResolvedValue({
      token: 'lk-jwt-token',
      url: 'wss://test.livekit.cloud',
      room: 'user-123',
    });
    const user = userEvent.setup();
    renderWithProviders(<TalkPage />);

    await user.click(screen.getByRole('button', { name: /start talking/i }));
    await screen.findByRole('button', { name: /mute microphone/i });

    await user.click(screen.getByRole('button', { name: /end session/i }));

    await waitFor(() => {
      expect(disconnectMock).toHaveBeenCalled();
    });
    // The talk page navigates to the dedicated summary route once the
    // WebRTC teardown completes. Living at its own URL means the
    // AppHeader's Sarjy → home link from the summary actually leaves
    // the surface instead of reverting same-page state.
    await waitFor(() => {
      expect(navigateMock).toHaveBeenCalledWith({ to: '/session-end' });
    });
    // The summary payload travels via sessionStorage so /session-end
    // can render the frozen view without re-mounting the LiveKit
    // session.
    const stash = sessionStorage.getItem('sarjy.session-summary.v1');
    expect(stash).toBeTruthy();
    const parsed = JSON.parse(stash!) as { signal: { reason: string } };
    expect(parsed.signal.reason).toBe('user_ended');
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

    await user.click(screen.getByRole('button', { name: /start talking/i }));
    await screen.findByRole('button', { name: /mute microphone/i });

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
