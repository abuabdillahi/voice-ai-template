import { createFileRoute, redirect } from '@tanstack/react-router';

import { supabase } from '@/lib/supabase';
import { LimberHome } from '@/components/home';

export const Route = createFileRoute('/')({
  beforeLoad: async () => {
    const { data } = await supabase.auth.getSession();
    if (!data.session) {
      throw redirect({ to: '/sign-in' });
    }
  },
  component: LimberHome,
});
