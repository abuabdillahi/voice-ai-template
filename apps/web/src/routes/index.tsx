import { Link, createFileRoute, redirect, useNavigate } from '@tanstack/react-router';

import { supabase } from '@/lib/supabase';
import { TalkPage } from '@/components/talk-page';
import { MemorySidebar } from '@/components/memory-sidebar';
import { Button } from '@/components/ui/button';

export const Route = createFileRoute('/')({
  // RequireAuth: a redirect-based route guard that runs before the
  // component mounts. Subsequent issues reuse this pattern for every
  // authenticated route.
  beforeLoad: async () => {
    const { data } = await supabase.auth.getSession();
    if (!data.session) {
      throw redirect({ to: '/sign-in' });
    }
  },
  component: HomeRoute,
});

function HomeRoute() {
  const navigate = useNavigate();

  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex items-center justify-between border-b border-[hsl(var(--border))] px-6 py-3">
        <h1 className="text-lg font-semibold">Voice AI assistant</h1>
        <nav className="flex items-center gap-2">
          <Button asChild variant="link" size="sm">
            <Link to="/history">History</Link>
          </Button>
          <Button asChild variant="link" size="sm">
            <Link to="/settings">Settings</Link>
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={async () => {
              await supabase.auth.signOut();
              void navigate({ to: '/sign-in' });
            }}
          >
            Sign out
          </Button>
        </nav>
      </header>
      <main className="flex flex-1 items-start justify-center gap-4 px-4 py-6">
        <TalkPage />
        <aside className="w-72 flex-shrink-0">
          <MemorySidebar />
        </aside>
      </main>
    </div>
  );
}
