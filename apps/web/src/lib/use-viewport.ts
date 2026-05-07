import { useCallback, useSyncExternalStore } from 'react';

/**
 * Track whether the viewport currently matches a media query. Built on
 * :func:`useSyncExternalStore` so the first paint already reflects the
 * real viewport — no flash of the wrong layout — and the value stays in
 * sync if the user resizes or rotates the device. Returns `false` in
 * environments without `window.matchMedia` (SSR, JSDOM by default), so
 * test renders default to the mobile layout unless the test wires up
 * `matchMedia` itself.
 */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (cb: () => void) => {
      if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
        return () => {};
      }
      const mql = window.matchMedia(query);
      mql.addEventListener('change', cb);
      return () => mql.removeEventListener('change', cb);
    },
    [query],
  );
  const getSnapshot = (): boolean => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return false;
    }
    return window.matchMedia(query).matches;
  };
  return useSyncExternalStore(subscribe, getSnapshot, () => false);
}

/** Tailwind `sm` breakpoint and up. */
export function useSmViewport(): boolean {
  return useMediaQuery('(min-width: 640px)');
}

/** Tailwind `lg` breakpoint and up. */
export function useLargeViewport(): boolean {
  return useMediaQuery('(min-width: 1024px)');
}
