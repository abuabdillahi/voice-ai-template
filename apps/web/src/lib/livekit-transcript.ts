import { useCallback, useState } from 'react';
import { type Room } from 'livekit-client';

import { useDataChannelTopic } from '@/lib/livekit-data-channel';

/**
 * Wire shape of the `lk.triage-state` data-channel topic. The agent
 * worker emits one of these every time `record_symptom` commits a new
 * slot value; the frontend slot panel renders the `slots` map directly.
 */
export interface TriageStatePayload {
  slots: Record<string, string>;
  session_id: string;
}

/**
 * One line in the live transcript panel.
 *
 * The `role` distinguishes the end user's transcribed audio from the
 * agent's response and from a tool call so the UI can render each
 * differently. The `id` is the LiveKit text-stream id (for user/
 * assistant entries) or the tool call id (for tool-call entries) so
 * subsequent chunks of the same utterance overwrite earlier ones.
 *
 * Tool-call entries arrive on a separate LiveKit text-stream topic
 * (`lk.tool-calls`) emitted by the agent worker on
 * `function_tools_executed`. Their `text` is the tool name; the
 * `args` and `result` are rendered in a collapsible panel.
 */
export interface TranscriptEntry {
  id: string;
  role: 'user' | 'assistant' | 'tool-call';
  text: string;
  final: boolean;
  args?: Record<string, unknown>;
  result?: string | null;
  error?: boolean;
  /** Wall-clock time the entry was first created, used for chronological ordering. */
  createdAt: number;
}

const TRANSCRIPTION_TOPIC = 'lk.transcription';
const TOOL_CALLS_TOPIC = 'lk.tool-calls';

interface ToolCallPayload {
  id: string;
  name: string;
  args?: Record<string, unknown>;
  result?: string | null;
  error?: boolean;
}

const DEDUP_WINDOW_MS = 5_000;

/**
 * Subscribes to the LiveKit Agents transcript topics and returns a
 * rolling list of transcript entries. The hook listens to two topics:
 *
 * - `lk.transcription` — user/assistant utterances (LiveKit Agents
 *   convention).
 * - `lk.tool-calls` — tool invocations forwarded by the agent worker
 *   when a function tool finishes.
 *
 * Entries are kept in chronological order so the talk page can render
 * a single, time-ordered timeline regardless of which topic produced
 * each line.
 */
export function useLivekitTranscript(room: Room | null): TranscriptEntry[] {
  const [entries, setEntries] = useState<TranscriptEntry[]>([]);
  const reset = useCallback(() => setEntries([]), []);

  const upsert = useCallback((entry: TranscriptEntry): void => {
    setEntries((prev) => {
      // Primary key: stream id. Same id ⇒ same utterance, later
      // chunk overwrites earlier (the live-typing case).
      const byId = prev.findIndex((e) => e.id === entry.id);
      if (byId !== -1) {
        const copy = prev.slice();
        copy[byId] = { ...entry, createdAt: prev[byId].createdAt };
        return copy;
      }
      // Secondary key: same role + same text within a short window.
      // The realtime model emits the user's transcription twice for
      // each utterance (server VAD + realtime model echo) under
      // different stream ids; without this collapse, every user line
      // shows up duplicated. Tool-call entries are exempt because
      // their `id` is already unique per dispatch.
      if (entry.role !== 'tool-call') {
        const trimmed = entry.text.trim();
        const recent = prev.findIndex(
          (e) =>
            e.role === entry.role &&
            e.text.trim() === trimmed &&
            entry.createdAt - e.createdAt < DEDUP_WINDOW_MS,
        );
        if (recent !== -1) return prev;
      }
      return [...prev, entry];
    });
  }, []);

  const localIdentity = room?.localParticipant.identity;
  const handleTranscript = useCallback(
    async (
      reader: {
        info: { id?: string; attributes?: Record<string, string> };
        readAll: () => Promise<string>;
      },
      participant: { identity: string },
    ): Promise<void> => {
      const text = await reader.readAll();
      const finalAttr = reader.info.attributes?.['lk.transcription_final'];
      const isFinal = finalAttr === 'true';
      const id = reader.info.id ?? `${participant.identity}-${Date.now()}`;
      const role: 'user' | 'assistant' =
        participant.identity === localIdentity ? 'user' : 'assistant';
      upsert({ id, role, text, final: isFinal, createdAt: Date.now() });
    },
    [upsert, localIdentity],
  );

  const handleToolCall = useCallback(
    async (reader: { readAll: () => Promise<string> }): Promise<void> => {
      const raw = await reader.readAll();
      let payload: ToolCallPayload | null = null;
      try {
        payload = JSON.parse(raw) as ToolCallPayload;
      } catch {
        return;
      }
      if (!payload) return;
      upsert({
        id: `tool-${payload.id}`,
        role: 'tool-call',
        text: payload.name,
        final: true,
        args: payload.args,
        result: payload.result ?? null,
        error: Boolean(payload.error),
        createdAt: Date.now(),
      });
    },
    [upsert],
  );

  useDataChannelTopic(room, TRANSCRIPTION_TOPIC, handleTranscript, { onDisconnect: reset });
  useDataChannelTopic(room, TOOL_CALLS_TOPIC, handleToolCall);

  return entries;
}
