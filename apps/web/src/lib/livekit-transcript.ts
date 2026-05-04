import { useEffect, useState } from 'react';
import { RoomEvent, type Room } from 'livekit-client';

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

  useEffect(() => {
    if (!room) {
      setEntries([]);
      return;
    }

    const upsert = (entry: TranscriptEntry): void => {
      setEntries((prev) => {
        const existing = prev.findIndex((e) => e.id === entry.id);
        if (existing === -1) return [...prev, entry];
        const copy = prev.slice();
        // Preserve the original createdAt so reorders don't happen
        // when later chunks of the same utterance arrive.
        copy[existing] = { ...entry, createdAt: prev[existing].createdAt };
        return copy;
      });
    };

    const handleTranscript = async (
      reader: {
        info: { id?: string; attributes?: Record<string, string>; topic?: string };
        readAll: () => Promise<string>;
      },
      participantInfo: { identity: string },
    ): Promise<void> => {
      if (reader.info.topic !== TRANSCRIPTION_TOPIC) return;
      const text = await reader.readAll();
      const finalAttr = reader.info.attributes?.['lk.transcription_final'];
      const isFinal = finalAttr === 'true';
      const id = reader.info.id ?? `${participantInfo.identity}-${Date.now()}`;
      const role: 'user' | 'assistant' =
        participantInfo.identity === room.localParticipant.identity ? 'user' : 'assistant';

      upsert({ id, role, text, final: isFinal, createdAt: Date.now() });
    };

    const handleToolCall = async (reader: {
      info: { id?: string; attributes?: Record<string, string>; topic?: string };
      readAll: () => Promise<string>;
    }): Promise<void> => {
      if (reader.info.topic !== TOOL_CALLS_TOPIC) return;
      const raw = await reader.readAll();
      let payload: ToolCallPayload | null = null;
      try {
        payload = JSON.parse(raw) as ToolCallPayload;
      } catch {
        // Malformed payloads are dropped; the agent always emits JSON.
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
    };

    // Some livekit-client versions expose registerTextStreamHandler;
    // the cast keeps us source-compatible without depending on a
    // specific minor.
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
    r.registerTextStreamHandler?.(TRANSCRIPTION_TOPIC, handleTranscript);
    r.registerTextStreamHandler?.(TOOL_CALLS_TOPIC, handleToolCall as unknown as StreamHandler);

    const reset = (): void => setEntries([]);
    room.on(RoomEvent.Disconnected, reset);

    return () => {
      r.unregisterTextStreamHandler?.(TRANSCRIPTION_TOPIC);
      r.unregisterTextStreamHandler?.(TOOL_CALLS_TOPIC);
      room.off(RoomEvent.Disconnected, reset);
    };
  }, [room]);

  return entries;
}
