import { Link, useNavigate } from '@tanstack/react-router';

import { supabase } from '@/lib/supabase';
import { SarjyWordmark } from '@/components/sarjy-logo';
import { ThemeSwitcher } from '@/components/theme-switcher';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

interface AppHeaderProps {
  active: 'talk' | 'history';
}

export function AppHeader({ active }: AppHeaderProps) {
  const navigate = useNavigate();

  return (
    <header className="sticky top-0 z-10 flex items-center justify-between border-b border-[hsl(var(--border))] bg-[hsl(var(--background))]/95 px-6 py-3 backdrop-blur supports-[backdrop-filter]:bg-[hsl(var(--background))]/85">
      <Link
        to="/"
        aria-label="Sarjy home"
        className="rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))]"
      >
        <SarjyWordmark size={26} />
      </Link>
      <nav className="flex items-center gap-1">
        <Button asChild variant="ghost" size="sm">
          <Link
            to="/"
            className={cn(
              active === 'talk'
                ? 'font-semibold text-[hsl(var(--foreground))]'
                : 'text-[hsl(var(--muted-foreground))]',
            )}
          >
            Talk
          </Link>
        </Button>
        <Button asChild variant="ghost" size="sm">
          <Link
            to="/history"
            className={cn(
              active === 'history'
                ? 'font-semibold text-[hsl(var(--foreground))]'
                : 'text-[hsl(var(--muted-foreground))]',
            )}
          >
            History
          </Link>
        </Button>
        <span className="mx-2 h-5 w-px bg-[hsl(var(--border))]" aria-hidden />
        <ThemeSwitcher />
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
  );
}
