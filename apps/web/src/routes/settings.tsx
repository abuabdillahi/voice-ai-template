import { Link, createFileRoute, redirect, useNavigate } from '@tanstack/react-router';

import { supabase } from '@/lib/supabase';
import { SettingsForm } from '@/components/settings-form';
import { Button } from '@/components/ui/button';

export const Route = createFileRoute('/settings')({
  beforeLoad: async () => {
    const { data } = await supabase.auth.getSession();
    if (!data.session) {
      throw redirect({ to: '/sign-in' });
    }
  },
  component: SettingsRoute,
});

function SettingsRoute() {
  const navigate = useNavigate();

  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex items-center justify-between border-b border-[hsl(var(--border))] px-6 py-3">
        <h1 className="text-lg font-semibold">Settings</h1>
        <nav className="flex items-center gap-2">
          <Button asChild variant="link" size="sm">
            <Link to="/">Talk</Link>
          </Button>
          <Button asChild variant="link" size="sm">
            <Link to="/history">History</Link>
          </Button>
        </nav>
      </header>
      <main className="flex flex-1 items-start justify-center px-4 py-6">
        <SettingsForm onSignedOut={() => void navigate({ to: '/sign-in' })} />
      </main>
    </div>
  );
}
