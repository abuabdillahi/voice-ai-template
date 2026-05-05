import { createFileRoute, redirect } from '@tanstack/react-router';

import { supabase } from '@/lib/supabase';
import { TriageHome } from '@/components/triage-home';

export const Route = createFileRoute('/')({
  beforeLoad: async () => {
    const { data } = await supabase.auth.getSession();
    if (!data.session) {
      throw redirect({ to: '/sign-in' });
    }
  },
  component: TriageHome,
});
