import { useState } from 'react';
import { type Room } from 'livekit-client';

import { useJsonDataChannelTopic } from '@/lib/livekit-data-channel';
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
  { key: 'location', label: 'Location', plain: 'Where it hurts' },
  { key: 'onset', label: 'Onset', plain: 'When it started' },
  { key: 'duration', label: 'Duration', plain: 'How long each episode' },
  { key: 'quality', label: 'Quality', plain: 'What it feels like' },
  { key: 'severity', label: 'Severity', plain: 'How bad, 0–10' },
  { key: 'aggravators', label: 'Aggravators', plain: 'What makes it worse' },
  { key: 'relievers', label: 'Relievers', plain: 'What makes it better' },
  { key: 'radiation', label: 'Radiation', plain: 'Does it travel' },
  { key: 'prior_episodes', label: 'Prior episodes', plain: 'Has this happened before' },
  { key: 'occupation_context', label: 'Desk / context', plain: 'Your workstation setup' },
] as const;

const TRIAGE_STATE_TOPIC = 'lk.triage-state';

const validateTriageState = (raw: unknown): TriageStatePayload | null => {
  if (!raw || typeof raw !== 'object') return null;
  const slots = (raw as { slots?: unknown }).slots;
  if (!slots || typeof slots !== 'object') return null;
  return raw as TriageStatePayload;
};

/**
 * Subscribes to the `lk.triage-state` topic and returns the current
 * slot map. The agent emits one frame per `record_symptom` commit; we
 * keep only the latest value because each frame carries the *full*
 * snapshot, not a delta.
 */
export function useLivekitTriageState(room: Room | null): Record<string, string> {
  const [slots, setSlots] = useState<Record<string, string>>({});
  useJsonDataChannelTopic<TriageStatePayload>(
    room,
    TRIAGE_STATE_TOPIC,
    validateTriageState,
    (payload) => setSlots(payload.slots),
    { onDisconnect: () => setSlots({}) },
  );
  return slots;
}
