import type { SVGProps } from 'react';

export interface SarjyLogoProps extends Omit<SVGProps<SVGSVGElement>, 'viewBox'> {
  size?: number;
}

/**
 * Sarjy mark — symmetric five-bar waveform with an amber accent dot.
 * Geometry and colours are kept in lockstep with `apps/web/public/favicon.svg`
 * so the inline mark, browser tab icon, and any future static export
 * read as the same logo. The hex colours (teal #0d9488 + amber #fbbf24)
 * are intentionally fixed across light and dark — a brand mark should
 * not theme-shift.
 */
export function SarjyLogo({ size = 32, ...rest }: SarjyLogoProps) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 64 64"
      width={size}
      height={size}
      role="img"
      aria-label="Sarjy"
      {...rest}
    >
      <g stroke="#0d9488" strokeWidth={6} strokeLinecap="round">
        <line x1={12} y1={22} x2={12} y2={42} />
        <line x1={22} y1={16} x2={22} y2={48} />
        <line x1={32} y1={10} x2={32} y2={54} />
        <line x1={42} y1={16} x2={42} y2={48} />
        <line x1={52} y1={22} x2={52} y2={42} />
      </g>
      <circle cx={56} cy={8} r={3} fill="#fbbf24" />
    </svg>
  );
}

interface SarjyWordmarkProps {
  size?: number;
}

export function SarjyWordmark({ size = 28 }: SarjyWordmarkProps) {
  return (
    <div className="flex items-center gap-2">
      <SarjyLogo size={size} />
      <span
        className="font-serif font-medium"
        style={{ fontSize: size * 0.86, color: 'hsl(var(--foreground))' }}
      >
        Sarjy
      </span>
    </div>
  );
}
