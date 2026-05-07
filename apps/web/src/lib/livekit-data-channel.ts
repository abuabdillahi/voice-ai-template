import { useEffect } from 'react';
import { RoomEvent, type Room } from 'livekit-client';

export type StreamReader = {
  info: { id?: string; attributes?: Record<string, string>; topic?: string };
  readAll: () => Promise<string>;
};

export type StreamHandler = (
  reader: StreamReader,
  participant: { identity: string },
) => Promise<void>;

type RoomWithTextStream = Room & {
  registerTextStreamHandler?: (topic: string, handler: StreamHandler) => void;
  unregisterTextStreamHandler?: (topic: string) => void;
};

/**
 * Subscribes a handler to one LiveKit data-channel topic for the
 * lifetime of the given room.
 *
 * Owns the boilerplate every consumer would otherwise repeat: the
 * `registerTextStreamHandler` cast (some livekit-client versions don't
 * advertise it on the public type), the topic filter, and the
 * Disconnected listener that lets state-holding hooks reset on room
 * teardown. The handler itself receives the raw reader and participant
 * so callers that need `info.attributes` or `participant.identity`
 * (the transcript hook) keep that fidelity.
 */
export function useDataChannelTopic(
  room: Room | null,
  topic: string,
  onMessage: StreamHandler,
  options?: { onDisconnect?: () => void },
): void {
  useEffect(() => {
    if (!room) {
      options?.onDisconnect?.();
      return;
    }
    const handler: StreamHandler = async (reader, participant) => {
      if (reader.info.topic !== topic) return;
      await onMessage(reader, participant);
    };
    const r = room as RoomWithTextStream;
    r.registerTextStreamHandler?.(topic, handler);
    const onDisconnect = options?.onDisconnect;
    if (onDisconnect) room.on(RoomEvent.Disconnected, onDisconnect);
    return () => {
      r.unregisterTextStreamHandler?.(topic);
      if (onDisconnect) room.off(RoomEvent.Disconnected, onDisconnect);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [room, topic]);
}

/**
 * Subscribes to a topic whose payload is a single JSON object.
 *
 * `validate` runs against `JSON.parse(raw)` and returns the typed
 * payload or `null` to drop the message — used for both schema
 * validation (e.g. `reason` is a string) and a malformed-JSON guard
 * (try/catch lives inside this helper, never in the caller).
 */
export function useJsonDataChannelTopic<T>(
  room: Room | null,
  topic: string,
  validate: (raw: unknown) => T | null,
  onMessage: (payload: T) => void,
  options?: { onDisconnect?: () => void },
): void {
  useDataChannelTopic(
    room,
    topic,
    async (reader) => {
      const raw = await reader.readAll();
      let parsed: unknown;
      try {
        parsed = JSON.parse(raw);
      } catch {
        return;
      }
      const payload = validate(parsed);
      if (payload === null) return;
      onMessage(payload);
    },
    options,
  );
}
