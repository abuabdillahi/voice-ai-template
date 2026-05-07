import { useEffect, useState } from 'react';

export type ThemeChoice = 'light' | 'dark' | 'system';

const STORAGE_KEY = 'sarjy.theme';
const EVENT = 'sarjy:theme';

export function readStoredTheme(): ThemeChoice {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === 'light' || v === 'dark' || v === 'system') return v;
  } catch {
    /* sessionStorage / localStorage may throw under sandboxing */
  }
  return 'system';
}

function systemPrefersDark(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-color-scheme: dark)').matches
  );
}

export function effectiveTheme(choice: ThemeChoice): 'light' | 'dark' {
  if (choice === 'system') return systemPrefersDark() ? 'dark' : 'light';
  return choice;
}

function applyDocumentAttr(choice: ThemeChoice): void {
  const root = document.documentElement;
  const eff = effectiveTheme(choice);
  if (eff === 'dark') root.setAttribute('data-theme', 'dark');
  else root.removeAttribute('data-theme');
}

export function setTheme(choice: ThemeChoice): void {
  try {
    localStorage.setItem(STORAGE_KEY, choice);
  } catch {
    /* ignore */
  }
  applyDocumentAttr(choice);
  window.dispatchEvent(new CustomEvent(EVENT, { detail: choice }));
}

/**
 * Initialise the document `data-theme` attribute from stored
 * preference. Call once before React mounts so the first paint matches
 * the saved theme (no light-flash on dark mode reload). Also wires up
 * a `prefers-color-scheme` media listener so the "system" choice
 * updates live when the OS palette changes.
 */
export function initTheme(): void {
  if (typeof window === 'undefined') return;
  const choice = readStoredTheme();
  applyDocumentAttr(choice);
  if (typeof window.matchMedia === 'function') {
    const mql = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = (): void => {
      if (readStoredTheme() === 'system') applyDocumentAttr('system');
    };
    if (typeof mql.addEventListener === 'function') {
      mql.addEventListener('change', onChange);
    } else if (typeof mql.addListener === 'function') {
      mql.addListener(onChange);
    }
  }
}

export function useTheme(): [ThemeChoice, (next: ThemeChoice) => void] {
  const [choice, setChoice] = useState<ThemeChoice>(() => readStoredTheme());
  useEffect(() => {
    const handler = (event: Event): void => {
      const detail = (event as CustomEvent<ThemeChoice>).detail;
      if (detail === 'light' || detail === 'dark' || detail === 'system') {
        setChoice(detail);
      }
    };
    window.addEventListener(EVENT, handler);
    return () => window.removeEventListener(EVENT, handler);
  }, []);
  return [choice, setTheme];
}
