import { useEffect, useState } from 'react';
import { createFileRoute, redirect, useNavigate } from '@tanstack/react-router';

import { supabase } from '@/lib/supabase';
import { AppHeader } from '@/components/app-header';
import {
  SessionSummary,
  readSessionSummary,
  type SessionSummaryStash,
} from '@/components/session-summary';

/**
 * Dedicated post-session summary route. The talk page navigates here
 * once the WebRTC teardown completes (either a user-driven End session
 * or the server-driven `room.delete` after an escalation script
 * finishes), passing the snapshot through sessionStorage. Living at a
 * stable URL means the AppHeader's Sarjy-mark → `/` navigation is a
 * real route change rather than a state reset on the same page.
 *
 * If the user lands here without a stash (deep link, browser refresh,
 * stash cleared), we redirect home — there's nothing to show.
 */
export const Route = createFileRoute('/session-end')({
  beforeLoad: async () => {
    const { data } = await supabase.auth.getSession();
    if (!data.session) {
      throw redirect({ to: '/sign-in' });
    }
  },
  component: SessionEndRoute,
});

function SessionEndRoute() {
  const navigate = useNavigate();
  const [stash, setStash] = useState<SessionSummaryStash | null>(null);
  const [resolved, setResolved] = useState(false);

  useEffect(() => {
    const found = readSessionSummary();
    setStash(found);
    setResolved(true);
    if (!found) {
      void navigate({ to: '/' });
    }
  }, [navigate]);

  if (!resolved || !stash) {
    return null;
  }

  return (
    <div className="flex min-h-screen flex-col">
      <AppHeader active="talk" />
      <SessionSummary
        signal={stash.signal}
        transcript={stash.transcript}
        triageSlots={stash.triageSlots}
        scrollToTopOnMount
      />
    </div>
  );
}
