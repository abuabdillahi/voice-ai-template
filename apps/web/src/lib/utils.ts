import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

/**
 * Canonical shadcn/ui class-name merger. Combines `clsx` (for conditional
 * class composition) with `tailwind-merge` (for de-duplicating conflicting
 * Tailwind utility classes) into a single helper.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
