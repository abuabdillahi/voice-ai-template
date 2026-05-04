import { createFileRoute, redirect, useNavigate } from '@tanstack/react-router';
import { useQuery } from '@tanstack/react-query';

import { supabase } from '@/lib/supabase';
import { useUser } from '@/lib/auth';
import { apiFetch } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

interface MeResponse {
  id: string;
  email: string;
}

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
  component: HomePage,
});

function HomePage() {
  const navigate = useNavigate();
  const { user, session } = useUser();

  const meQuery = useQuery({
    queryKey: ['me', session?.access_token ?? null],
    queryFn: () => apiFetch<MeResponse>('/me'),
    enabled: !!session,
  });

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Signed in</CardTitle>
          <CardDescription>
            The /me API call confirms the FastAPI backend can verify the Supabase access token.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="text-sm">
            <span className="font-medium">Supabase user email:&nbsp;</span>
            {user?.email ?? '—'}
          </div>
          <div className="text-sm">
            <span className="font-medium">/me endpoint email:&nbsp;</span>
            {meQuery.isLoading
              ? 'loading…'
              : meQuery.isError
                ? 'error'
                : (meQuery.data?.email ?? '—')}
          </div>
          <Button
            variant="outline"
            onClick={async () => {
              await supabase.auth.signOut();
              void navigate({ to: '/sign-in' });
            }}
          >
            Sign out
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
