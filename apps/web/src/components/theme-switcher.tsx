import { Monitor, Moon, Sun } from 'lucide-react';

import { type ThemeChoice, useTheme } from '@/lib/theme';
import { cn } from '@/lib/utils';

const OPTIONS: ReadonlyArray<{ value: ThemeChoice; label: string; Icon: typeof Sun }> = [
  { value: 'light', label: 'Light', Icon: Sun },
  { value: 'dark', label: 'Dark', Icon: Moon },
  { value: 'system', label: 'System', Icon: Monitor },
];

/**
 * Three-state theme pill (Light / Dark / System) that drives the
 * document-level `data-theme` attribute via :data:`setTheme`. The
 * choice is persisted in `localStorage` and a `prefers-color-scheme`
 * listener (set up in :func:`initTheme`) keeps "system" live.
 */
export function ThemeSwitcher() {
  const [choice, setChoice] = useTheme();
  return (
    <div
      role="radiogroup"
      aria-label="Theme"
      className="inline-flex items-center rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--muted))] p-0.5"
    >
      {OPTIONS.map(({ value, label, Icon }) => {
        const active = choice === value;
        return (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={label}
            title={label}
            onClick={() => setChoice(value)}
            className={cn(
              'inline-flex h-6 w-7 items-center justify-center rounded-full transition-colors',
              active
                ? 'bg-[hsl(var(--card))] text-[hsl(var(--foreground))] shadow-sm'
                : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]',
            )}
          >
            <Icon className="h-3.5 w-3.5" />
          </button>
        );
      })}
    </div>
  );
}
