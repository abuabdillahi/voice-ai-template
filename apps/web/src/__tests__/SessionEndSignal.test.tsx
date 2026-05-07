import { describe, expect, it, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { RoomEvent } from 'livekit-client';

import { useSessionEndSignal } from '@/lib/livekit-session-end';

const SESSION_END_TOPIC = 'lk.session-end';

type StreamReader = {
  info: { topic?: string };
  readAll: () => Promise<string>;
};

type StreamHandler = (reader: StreamReader, participantInfo: { identity: string }) => Promise<void>;

class FakeRoom {
  handlers = new Map<string, StreamHandler>();
  listeners = new Map<string, Set<(...args: unknown[]) => void>>();

  registerTextStreamHandler = (topic: string, handler: StreamHandler): void => {
    this.handlers.set(topic, handler);
  };

  unregisterTextStreamHandler = (topic: string): void => {
    this.handlers.delete(topic);
  };

  on = (event: string, listener: (...args: unknown[]) => void): this => {
    if (!this.listeners.has(event)) this.listeners.set(event, new Set());
    this.listeners.get(event)!.add(listener);
    return this;
  };

  off = (event: string, listener: (...args: unknown[]) => void): this => {
    this.listeners.get(event)?.delete(listener);
    return this;
  };

  emitText(topic: string, body: string): Promise<void> {
    const handler = this.handlers.get(topic);
    if (!handler) return Promise.resolve();
    return handler(
      {
        info: { topic },
        readAll: async () => body,
      },
      { identity: 'agent' },
    );
  }
}

describe('useSessionEndSignal', () => {
  let room: FakeRoom;

  beforeEach(() => {
    room = new FakeRoom();
  });

  it('returns null before any event is received', () => {
    const { result } = renderHook(() =>
      useSessionEndSignal(room as unknown as Parameters<typeof useSessionEndSignal>[0]),
    );
    expect(result.current).toBeNull();
  });

  it('returns the parsed payload after a well-formed event', async () => {
    const { result } = renderHook(() =>
      useSessionEndSignal(room as unknown as Parameters<typeof useSessionEndSignal>[0]),
    );
    await act(async () => {
      await room.emitText(
        SESSION_END_TOPIC,
        JSON.stringify({ reason: 'escalation', tier: 'emergent' }),
      );
    });
    await waitFor(() => {
      expect(result.current).toEqual({ reason: 'escalation', tier: 'emergent' });
    });
  });

  it('ignores events on other topics', async () => {
    const { result } = renderHook(() =>
      useSessionEndSignal(room as unknown as Parameters<typeof useSessionEndSignal>[0]),
    );
    // Some other-topic emission via a separately-registered handler
    // must not produce a non-null signal. The hook only registers the
    // session-end topic handler, so an emission on an unregistered
    // topic is a noop by construction.
    await act(async () => {
      await room.emitText('lk.tool-calls', '{"id":"x"}');
    });
    expect(result.current).toBeNull();
  });

  it('returns null (and does not throw) for malformed JSON', async () => {
    const { result } = renderHook(() =>
      useSessionEndSignal(room as unknown as Parameters<typeof useSessionEndSignal>[0]),
    );
    await act(async () => {
      await room.emitText(SESSION_END_TOPIC, 'not-json');
    });
    expect(result.current).toBeNull();
  });

  it('cleans up its subscription on unmount', () => {
    const { unmount } = renderHook(() =>
      useSessionEndSignal(room as unknown as Parameters<typeof useSessionEndSignal>[0]),
    );
    expect(room.handlers.has(SESSION_END_TOPIC)).toBe(true);
    unmount();
    expect(room.handlers.has(SESSION_END_TOPIC)).toBe(false);
  });

  it('keeps the signal latched after the room disconnects', async () => {
    // Once a session-end signal has been received, it must persist for
    // the lifetime of the page. The 500ms audio-drain timer in
    // `talk-page.tsx` triggers `room.disconnect()`, which fires
    // `RoomEvent.Disconnected` synchronously — if the hook reset on
    // that event, the EndOfConversationCard would vanish ~half a second
    // after it appeared and the user would land back on the regular Talk
    // page with no record of why the conversation ended.
    const { result } = renderHook(() =>
      useSessionEndSignal(room as unknown as Parameters<typeof useSessionEndSignal>[0]),
    );
    await act(async () => {
      await room.emitText(
        SESSION_END_TOPIC,
        JSON.stringify({ reason: 'escalation', tier: 'urgent' }),
      );
    });
    await waitFor(() => {
      expect(result.current).toEqual({ reason: 'escalation', tier: 'urgent' });
    });
    act(() => {
      const handlers = room.listeners.get(RoomEvent.Disconnected);
      handlers?.forEach((h) => h());
    });
    expect(result.current).toEqual({ reason: 'escalation', tier: 'urgent' });
  });

  it('clears the signal when the room reference itself goes away', () => {
    // Hook prop change to null (page unmount path / sign-out) does
    // clear the signal — this is the natural reset, not a transport
    // disconnect.
    const { result, rerender } = renderHook(
      ({ r }: { r: FakeRoom | null }) =>
        useSessionEndSignal(r as unknown as Parameters<typeof useSessionEndSignal>[0]),
      { initialProps: { r: room as FakeRoom | null } },
    );
    expect(result.current).toBeNull();
    rerender({ r: null });
    expect(result.current).toBeNull();
  });
});
