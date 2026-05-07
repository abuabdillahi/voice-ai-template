export type VoiceState = 'idle' | 'connecting' | 'listening' | 'thinking' | 'speaking' | 'muted';

const STATE_COPY: Record<VoiceState, { primary: string; sub: string }> = {
  idle: { primary: 'Ready.', sub: 'Press Start to begin.' },
  // `connecting` covers the window between the room being established
  // and Sarjy delivering its opening turn. The copy must not invite
  // the user to speak: Sarjy is the one who initiates, and a "I'm
  // listening" prompt at this moment leads users to start talking
  // over a greeting that hasn't arrived yet. The phrasing is
  // deliberately indirect — describes what's happening rather than
  // instructing the user to wait.
  connecting: { primary: 'Just a moment…', sub: 'Sarjy will be with you shortly.' },
  listening: { primary: "I'm listening.", sub: 'Take your time.' },
  thinking: { primary: 'Thinking…', sub: 'Pulling that together.' },
  speaking: { primary: "I'm speaking.", sub: 'Speak up to jump in.' },
  muted: { primary: "You're muted.", sub: "Tap unmute when you're ready." },
};

export function voiceStateCopy(state: VoiceState): { primary: string; sub: string } {
  return STATE_COPY[state];
}

interface VoiceDotProps {
  state: VoiceState;
  size?: number;
}

const TEAL = 'hsl(var(--primary))';

export function VoiceDot({ state, size = 64 }: VoiceDotProps) {
  const colorVar =
    state === 'muted'
      ? 'var(--muted-foreground)'
      : state === 'thinking'
        ? 'var(--accent)'
        : 'var(--primary)';
  const color = `hsl(${colorVar})`;
  const showRing = state === 'listening' || state === 'speaking';
  // `connecting` is intentionally non-breathing — a static dot reads as
  // "wait, hold on" while the breathing pulse on `listening` /
  // `speaking` reads as "the loop is live, you can act".
  const breathing = state === 'idle' || state === 'listening' || state === 'speaking';

  return (
    <div
      role="status"
      aria-label={`Agent ${state}`}
      className="relative inline-flex items-center justify-center"
      style={{ width: size, height: size }}
    >
      {showRing ? (
        <span
          aria-hidden
          className="sarjy-voice-ring absolute inset-0 rounded-full"
          style={{
            border: `1.5px solid ${color}`,
            animation: 'sarjy-pulse-ring 2.2s ease-out infinite',
          }}
        />
      ) : null}
      <span
        aria-hidden
        className="sarjy-voice-dot rounded-full"
        style={{
          width: size * 0.42,
          height: size * 0.42,
          background: color,
          boxShadow: state === 'muted' ? 'none' : `0 0 ${size * 0.45}px hsl(${colorVar} / 0.33)`,
          animation: breathing ? 'sarjy-breathe 3.2s ease-in-out infinite' : 'none',
          transition: 'background 200ms',
        }}
      />
      {state === 'thinking' ? (
        <div aria-hidden className="absolute flex gap-[3px]">
          {[0, 1, 2].map((i) => (
            <span
              key={i}
              className="sarjy-thinking-dot rounded-full bg-white"
              style={{
                width: 5,
                height: 5,
                animation: `sarjy-thinking 1.2s ease-in-out ${i * 0.16}s infinite`,
              }}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

interface MicMeterProps {
  level: number;
  active?: boolean;
}

export function MicMeter({ level, active = true }: MicMeterProps) {
  const bars = 5;
  return (
    <div aria-hidden className="flex items-end gap-[3px]" style={{ height: 18 }}>
      {Array.from({ length: bars }).map((_, i) => {
        const threshold = (i + 1) / bars;
        const lit = active && level >= threshold * 0.85;
        const h = 4 + i * 3;
        return (
          <span
            key={i}
            className="rounded-[1.5px] transition-colors duration-75"
            style={{
              width: 3,
              height: h,
              background: lit ? TEAL : 'hsl(var(--border))',
            }}
          />
        );
      })}
    </div>
  );
}
