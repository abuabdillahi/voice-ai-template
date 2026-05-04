/**
 * Frontend mirror of `core.preferences.OPENAI_REALTIME_VOICES`.
 *
 * The list is duplicated here rather than read from the API at
 * runtime because the catalogue is small, fixed per template release,
 * and the settings page needs to render the selector synchronously
 * before any network round-trip. When a downstream fork adds a new
 * OpenAI Realtime voice it must add it both here *and* in
 * `packages/core/core/preferences.py` — the test suite asserts the
 * lists agree so a one-sided edit fails CI.
 */
export const VOICE_OPTIONS = [
  'alloy',
  'ash',
  'ballad',
  'coral',
  'echo',
  'sage',
  'shimmer',
  'verse',
] as const;

export type VoiceId = (typeof VOICE_OPTIONS)[number];

export function isVoiceId(value: unknown): value is VoiceId {
  return typeof value === 'string' && (VOICE_OPTIONS as readonly string[]).includes(value);
}
