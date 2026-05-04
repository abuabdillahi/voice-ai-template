import { createClient } from '@supabase/supabase-js';

const url = import.meta.env.VITE_SUPABASE_URL;
// Prefer the new publishable key name. Fall back to the legacy anon key
// so .env files cloned before issue 13 keep working until the user
// renames the variable.
const publishableKey =
  import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY ?? import.meta.env.VITE_SUPABASE_ANON_KEY;

if (!url || !publishableKey) {
  // The component tree mounts the AuthProvider before any auth call is
  // made, so this throw surfaces during local boot rather than as a 401
  // mid-flow.
  throw new Error(
    'Missing Supabase env vars: set VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY in the repo-root .env (Vite reads it via envDir).',
  );
}

export const supabase = createClient(url, publishableKey, {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
    detectSessionInUrl: true,
  },
});
