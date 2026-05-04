import { useEffect, useState } from 'react';
import { RoomEvent, type Room } from 'livekit-client';

/**
 * One line in the live transcript panel. The role distinguishes the
 * end user's transcribed audio from the agent's response so the UI
 * can render them differently. The id is the LiveKit text-stream id
 * so subsequent chunks of the same utterance overwrite earlier ones.
 */
export interface TranscriptEntry {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  final: boolean;
}

/**
 * Subscribes to the LiveKit Agents transcript topic and returns a
 * rolling list of transcript entries. The hook is intentionally
 * small: it owns no business logic, just the wiring between the
 * room's text-stream events and React state.
 *
 * The agent publishes transcripts on the `lk.transcription` topic
 * (LiveKit Agents convention). User entries arrive with their
 * participant identity matching the local participant; everything
 * else is treated as the assistant.
 */
export function useLivekitTranscript(room: Room | null): TranscriptEntry[] {
  const [entries, setEntries] = useState<TranscriptEntry[]>([]);

  useEffect(() => {
    if (!room) {
      setEntries([]);
      return;
    }

    const handleTextStream = async (
      reader: {
        info: { id?: string; attributes?: Record<string, string>; topic?: string };
        readAll: () => Promise<string>;
      },
      participantInfo: { identity: string },
    ): Promise<void> => {
      if (reader.info.topic !== 'lk.transcription') return;
      const text = await reader.readAll();
      const finalAttr = reader.info.attributes?.['lk.transcription_final'];
      const isFinal = finalAttr === 'true';
      const id = reader.info.id ?? `${participantInfo.identity}-${Date.now()}`;
      const role: 'user' | 'assistant' =
        participantInfo.identity === room.localParticipant.identity ? 'user' : 'assistant';

      setEntries((prev) => {
        const existing = prev.findIndex((entry) => entry.id === id);
        const next: TranscriptEntry = { id, role, text, final: isFinal };
        if (existing === -1) return [...prev, next];
        const copy = prev.slice();
        copy[existing] = next;
        return copy;
      });
    };

    // Some livekit-client versions expose registerTextStreamHandler;
    // the cast keeps us source-compatible without depending on a
    // specific minor.
    const r = room as unknown as {
      registerTextStreamHandler?: (topic: string, handler: typeof handleTextStream) => void;
      unregisterTextStreamHandler?: (topic: string) => void;
    };
    r.registerTextStreamHandler?.('lk.transcription', handleTextStream);

    const reset = (): void => setEntries([]);
    room.on(RoomEvent.Disconnected, reset);

    return () => {
      r.unregisterTextStreamHandler?.('lk.transcription');
      room.off(RoomEvent.Disconnected, reset);
    };
  }, [room]);

  return entries;
}
