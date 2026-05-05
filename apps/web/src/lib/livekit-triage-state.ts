import { useEffect, useState } from 'react';
import { RoomEvent, type Room } from 'livekit-client';

import type { TriageStatePayload } from '@/lib/livekit-transcript';

/**
 * Slot vocabulary the agent emits, in display order. Mirrors
 * `core.triage.SLOT_NAMES` on the Python side. Slots not yet disclosed
 * are rendered as a placeholder rather than hidden — this is the
 * "demo legibility" lever the issue calls out: making the OPQRST
 * backbone visible proves the model is structuring the conversation
 * rather than free-styling.
 */
export const TRIAGE_SLOTS = [
  { key: 'location', label: 'Location' },
  { key: 'onset', label: 'Onset' },
  { key: 'duration', label: 'Duration' },
  { key: 'quality', label: 'Quality' },
  { key: 'severity', label: 'Severity' },
  { key: 'aggravators', label: 'Aggravators' },
  { key: 'relievers', label: 'Relievers' },
  { key: 'radiation', label: 'Radiation' },
  { key: 'prior_episodes', label: 'Prior episodes' },
  { key: 'occupation_context', label: 'Desk / context' },
] as const;

const TRIAGE_STATE_TOPIC = 'lk.triage-state';

/**
 * Subscribes to the `lk.triage-state` topic and returns the current
 * slot map. The agent emits one frame per `record_symptom` commit; we
 * keep only the latest value because each frame carries the *full*
 * snapshot, not a delta.
 */
export function useLivekitTriageState(room: Room | null): Record<string, string> {
  const [slots, setSlots] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!room) {
      setSlots({});
      return;
    }

    const handle = async (reader: {
      info: { topic?: string };
      readAll: () => Promise<string>;
    }): Promise<void> => {
      if (reader.info.topic !== TRIAGE_STATE_TOPIC) return;
      const raw = await reader.readAll();
      let payload: TriageStatePayload | null = null;
      try {
        payload = JSON.parse(raw) as TriageStatePayload;
      } catch {
        // Malformed payloads are dropped; the agent always emits JSON.
        return;
      }
      if (!payload || typeof payload.slots !== 'object' || payload.slots === null) return;
      setSlots(payload.slots);
    };

    type StreamReader = {
      info: { id?: string; attributes?: Record<string, string>; topic?: string };
      readAll: () => Promise<string>;
    };
    type StreamHandler = (
      reader: StreamReader,
      participantInfo: { identity: string },
    ) => Promise<void>;
    const r = room as unknown as {
      registerTextStreamHandler?: (topic: string, handler: StreamHandler) => void;
      unregisterTextStreamHandler?: (topic: string) => void;
    };
    r.registerTextStreamHandler?.(TRIAGE_STATE_TOPIC, handle as unknown as StreamHandler);

    const reset = (): void => setSlots({});
    room.on(RoomEvent.Disconnected, reset);

    return () => {
      r.unregisterTextStreamHandler?.(TRIAGE_STATE_TOPIC);
      room.off(RoomEvent.Disconnected, reset);
    };
  }, [room]);

  return slots;
}
