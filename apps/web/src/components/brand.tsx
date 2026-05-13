import type { SVGProps } from 'react';

import { cn } from '@/lib/utils';

export interface BrookAvatarProps extends Omit<SVGProps<SVGSVGElement>, 'viewBox'> {
  size?: number;
  listening?: boolean;
  className?: string;
}

/**
 * Brook — the voice agent. Two stacked ripples on a teal-soft disc.
 * The mark stands in for the assistant wherever the user encounters
 * Brook: transcript bubble avatars, the pre-connect "Meet your
 * assistant" card, the in-session status row. Teal is Brook's
 * brand-constant — the colour stays close across light and dark
 * themes so the agent never reads as "just another button".
 */
export function BrookAvatar({
  size = 32,
  listening = false,
  className,
  ...rest
}: BrookAvatarProps) {
  return (
    <span
      className={cn('relative inline-flex flex-none items-center justify-center', className)}
      style={{
        width: size,
        height: size,
        borderRadius: '50%',
        background: 'hsl(var(--primary-soft))',
      }}
    >
      {listening ? (
        <span
          aria-hidden
          className="absolute inset-0 rounded-full"
          style={{
            border: '1.5px solid hsl(var(--primary))',
            animation: 'limber-pulse-ring 2.2s ease-out infinite',
          }}
        />
      ) : null}
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 28 28"
        width={size * 0.55}
        height={size * 0.55}
        role="img"
        aria-label="Brook"
        {...rest}
      >
        <g stroke="hsl(var(--primary))" strokeWidth={2.2} strokeLinecap="round" fill="none">
          <path d="M3 10 C 7 7, 11 13, 15 10 S 23 7, 25 10" />
          <path d="M3 16 C 7 13, 11 19, 15 16 S 23 13, 25 16" />
        </g>
      </svg>
    </span>
  );
}

interface LimberWordmarkProps {
  size?: number;
  className?: string;
}

/**
 * limber wordmark — "limber." set in Inter 700 with tight tracking and
 * an orange period anchor. The period is the brand mark; never split
 * the word from its punctuation.
 */
export function LimberWordmark({ size = 22, className }: LimberWordmarkProps) {
  return (
    <span
      aria-label="limber"
      className={className}
      style={{
        font: `700 ${size}px/1 'Inter', sans-serif`,
        letterSpacing: '-0.035em',
        color: 'hsl(var(--foreground))',
        display: 'inline-flex',
        alignItems: 'baseline',
      }}
    >
      limber<span style={{ color: 'hsl(var(--accent))' }}>.</span>
    </span>
  );
}
