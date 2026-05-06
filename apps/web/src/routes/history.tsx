import { Outlet, createFileRoute } from '@tanstack/react-router';

/**
 * Layout-only parent for the `/history` and `/history/$id` routes.
 *
 * Each child route renders its own header (the list and the detail
 * pages are visually distinct enough that a shared shell would be
 * lossy), so this parent is a transparent passthrough that just
 * mounts the matched child via `<Outlet />`. Without this `<Outlet />`
 * the detail route silently fails to render — TanStack Router treats
 * `history.$id.tsx` as a child of `history.tsx` purely from the
 * filename prefix.
 */
export const Route = createFileRoute('/history')({
  component: HistoryLayout,
});

function HistoryLayout() {
  return <Outlet />;
}
