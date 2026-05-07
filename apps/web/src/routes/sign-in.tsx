import { useEffect } from 'react';
import { createFileRoute, useNavigate } from '@tanstack/react-router';

import { useUser } from '@/lib/auth';
import { SignInForm } from '@/components/sign-in-form';

export const Route = createFileRoute('/sign-in')({
  component: SignInPage,
});

function SignInPage() {
  const navigate = useNavigate();
  const { session } = useUser();

  // If we already have a session, navigate home.
  useEffect(() => {
    if (session) {
      void navigate({ to: '/' });
    }
  }, [session, navigate]);

  return <SignInForm onSignedIn={() => void navigate({ to: '/' })} />;
}
