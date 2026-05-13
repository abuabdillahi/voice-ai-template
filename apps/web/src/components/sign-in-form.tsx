import { useCallback, useState, useSyncExternalStore } from 'react';
import { useForm, type UseFormReturn } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { ArrowRight, Eye, EyeOff, Info } from 'lucide-react';

import { supabase } from '@/lib/supabase';
import { BrookAvatar, LimberWordmark } from '@/components/brand';
import { ThemeSwitcher } from '@/components/theme-switcher';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { cn } from '@/lib/utils';

const formSchema = z.object({
  email: z.string().email({ message: 'Enter a valid email address.' }),
  password: z.string().min(8, { message: 'Password must be at least 8 characters.' }),
});

type FormValues = z.infer<typeof formSchema>;
type Mode = 'sign-in' | 'sign-up';

export interface SignInFormProps {
  /** Called once a successful sign-in returns. */
  onSignedIn?: () => void;
}

const LG_QUERY = '(min-width: 1024px)';

/**
 * Track whether the viewport is at or above the `lg` Tailwind breakpoint.
 * Uses :func:`useSyncExternalStore` so the first paint already reflects
 * the real viewport — no flash of the wrong layout — and stays in sync
 * if the user resizes or rotates the device.
 */
function useLargeViewport(): boolean {
  const subscribe = useCallback((cb: () => void) => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return () => {};
    }
    const mql = window.matchMedia(LG_QUERY);
    mql.addEventListener('change', cb);
    return () => mql.removeEventListener('change', cb);
  }, []);
  const getSnapshot = (): boolean => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return false;
    }
    return window.matchMedia(LG_QUERY).matches;
  };
  return useSyncExternalStore(subscribe, getSnapshot, () => false);
}

interface LayoutProps {
  mode: Mode;
  onModeChange: (next: Mode) => void;
  form: UseFormReturn<FormValues>;
  onSubmit: (values: FormValues) => Promise<void>;
  showPassword: boolean;
  onTogglePassword: () => void;
  submitError: string | null;
  info: string | null;
}

/**
 * Auth surface. Renders the limber two-pane desktop layout on `lg` and
 * above and a single-column mobile layout below it. Both columns share
 * the active theme — no half-light / half-dark split — and introduce
 * Brook (the agent) as the calm voice the user will actually be
 * talking to.
 */
export function SignInForm({ onSignedIn }: SignInFormProps) {
  const [mode, setMode] = useState<Mode>('sign-in');
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const isLarge = useLargeViewport();

  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: { email: '', password: '' },
  });

  async function onSubmit(values: FormValues) {
    setSubmitError(null);
    setInfo(null);

    if (mode === 'sign-in') {
      const { error } = await supabase.auth.signInWithPassword(values);
      if (error) {
        setSubmitError(error.message);
        return;
      }
      onSignedIn?.();
    } else {
      const { error } = await supabase.auth.signUp(values);
      if (error) {
        setSubmitError(error.message);
        return;
      }
      setInfo('Account created. Open the verification link in your email, then sign in.');
      setMode('sign-in');
    }
  }

  function changeMode(next: Mode) {
    setSubmitError(null);
    setInfo(null);
    setMode(next);
  }

  const layoutProps: LayoutProps = {
    mode,
    onModeChange: changeMode,
    form,
    onSubmit,
    showPassword,
    onTogglePassword: () => setShowPassword((v) => !v),
    submitError,
    info,
  };

  return isLarge ? <DesktopLayout {...layoutProps} /> : <MobileLayout {...layoutProps} />;
}

// ---------------------------------------------------------------------------
// Mobile layout — single column. limber hero on top, Brook intro card on
// sign-in, then the auth form.
// ---------------------------------------------------------------------------

function MobileLayout({
  mode,
  onModeChange,
  form,
  onSubmit,
  showPassword,
  onTogglePassword,
  submitError,
  info,
}: LayoutProps) {
  const isSignup = mode === 'sign-up';
  return (
    <div className="flex min-h-screen flex-col bg-[hsl(var(--background))]">
      <header className="flex items-center justify-between px-6 pt-5 pb-3">
        <LimberWordmark size={22} />
        <ThemeSwitcher />
      </header>

      <div className="px-6 pt-3">
        <span className="limber-eyebrow">{isSignup ? 'Create account' : 'Welcome back'}</span>
        <h1 className="mt-2 mb-2 font-sans text-[34px] font-bold leading-[1.05] tracking-[-0.035em]">
          {isSignup ? (
            <>
              Set up
              <br />
              your limber.
            </>
          ) : (
            <>
              Less stiff
              <br />
              <span style={{ color: 'hsl(var(--accent))' }}>by Friday.</span>
            </>
          )}
        </h1>
        <p className="mt-3 text-[14px] leading-[1.5] text-[hsl(var(--muted-foreground))]">
          {isSignup
            ? 'Brook will introduce themselves first. Then you talk.'
            : 'Five minutes of voice. A plan you can actually follow.'}
        </p>
      </div>

      {!isSignup ? (
        <div className="mx-6 mt-5 flex items-center gap-3 rounded-2xl bg-[hsl(var(--secondary))] p-3.5">
          <BrookAvatar size={44} listening />
          <div className="min-w-0 flex-1">
            <div className="text-[10.5px] font-semibold uppercase tracking-[0.06em] text-[hsl(var(--muted-foreground))]">
              You&apos;ll be talking to
            </div>
            <div className="text-[15px] font-bold text-[hsl(var(--foreground))]">Brook</div>
            <div className="mt-0.5 text-[11.5px] text-[hsl(var(--muted-foreground))]">
              Calm. Listens. Not a doctor.
            </div>
          </div>
        </div>
      ) : null}

      <div role="tablist" aria-label="Auth mode" className="mt-5 flex gap-1 px-6">
        {(
          [
            { k: 'sign-in', label: 'Sign in' },
            { k: 'sign-up', label: 'Create account' },
          ] as const
        ).map((t) => {
          const active = t.k === mode;
          return (
            <button
              key={t.k}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => onModeChange(t.k)}
              className={cn(
                'flex-1 border-b-2 py-2.5 text-center text-[13.5px] font-semibold transition-colors',
                active
                  ? 'border-[hsl(var(--foreground))] text-[hsl(var(--foreground))]'
                  : 'border-transparent text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]',
              )}
            >
              {t.label}
            </button>
          );
        })}
      </div>

      <Form {...form}>
        <form
          onSubmit={form.handleSubmit(onSubmit)}
          noValidate
          className="flex flex-1 flex-col gap-3 px-6 pt-5 pb-6"
        >
          <FormField
            control={form.control}
            name="email"
            render={({ field }) => (
              <FormItem className="space-y-1.5">
                <FormLabel className="text-[12.5px] font-semibold text-[hsl(var(--foreground))]">
                  Email
                </FormLabel>
                <FormControl>
                  <Input
                    type="email"
                    autoComplete="email"
                    placeholder="you@work.com"
                    className="h-12 rounded-xl text-[15px]"
                    {...field}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="password"
            render={({ field }) => (
              <FormItem className="space-y-1.5">
                <div className="flex items-baseline justify-between">
                  <FormLabel className="text-[12.5px] font-semibold text-[hsl(var(--foreground))]">
                    Password
                  </FormLabel>
                  {!isSignup ? (
                    <span className="text-[11.5px] text-[hsl(var(--muted-foreground))]">
                      {/* Forgot-password flow not yet wired; placeholder for future. */}
                      Forgot?
                    </span>
                  ) : null}
                </div>
                <div className="relative">
                  <FormControl>
                    <Input
                      type={showPassword ? 'text' : 'password'}
                      autoComplete={isSignup ? 'new-password' : 'current-password'}
                      placeholder={isSignup ? 'At least 8 characters' : '••••••••'}
                      className="h-12 rounded-xl pr-11 text-[15px]"
                      {...field}
                    />
                  </FormControl>
                  <button
                    type="button"
                    onClick={onTogglePassword}
                    aria-label={showPassword ? 'Hide password' : 'Show password'}
                    className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1.5 text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
                  >
                    {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
                <FormMessage />
              </FormItem>
            )}
          />

          {submitError ? (
            <div
              role="alert"
              className="rounded-md border border-[hsl(var(--destructive))]/30 bg-[hsl(var(--destructive))]/5 px-3 py-2 text-sm font-medium text-[hsl(var(--destructive))]"
            >
              {submitError}
            </div>
          ) : null}
          {info ? (
            <div
              role="status"
              className="flex gap-2.5 rounded-md border border-[hsl(var(--primary-soft-border))] bg-[hsl(var(--primary-soft))] px-3 py-2.5 text-[13px] leading-snug text-[hsl(var(--primary-soft-fg))]"
            >
              <Info className="mt-0.5 h-4 w-4 flex-none text-[hsl(var(--primary-soft-fg))]" />
              <span>{info}</span>
            </div>
          ) : null}

          <Button
            type="submit"
            className="mt-2 h-12 w-full rounded-xl bg-[hsl(var(--foreground))] text-[14.5px] font-semibold text-[hsl(var(--background))] hover:bg-[hsl(var(--foreground))]/90"
            disabled={form.formState.isSubmitting}
          >
            {form.formState.isSubmitting ? 'Working…' : isSignup ? 'Create account' : 'Sign in'}
            <ArrowRight className="ml-1.5 h-4 w-4" style={{ color: 'hsl(var(--accent))' }} />
          </Button>

          <div className="mt-auto pt-5 text-center text-[11.5px] leading-[1.5] text-[hsl(var(--muted-foreground))]">
            By continuing you agree to the{' '}
            <a
              href="#"
              className="text-[hsl(var(--foreground))] underline-offset-2 hover:underline"
            >
              Terms
            </a>{' '}
            and acknowledge that limber isn&apos;t a medical device.
          </div>
        </form>
      </Form>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Desktop layout — both columns share the active theme. Left: limber hero
// + Brook intro card. Right: auth form.
// ---------------------------------------------------------------------------

function DesktopLayout({
  mode,
  onModeChange,
  form,
  onSubmit,
  showPassword,
  onTogglePassword,
  submitError,
  info,
}: LayoutProps) {
  const isSignup = mode === 'sign-up';
  return (
    <div className="grid min-h-screen w-full grid-cols-[1.05fr_1fr] bg-[hsl(var(--background))]">
      <aside
        aria-label="About limber + Brook"
        className="relative flex flex-col justify-between overflow-hidden border-r border-[hsl(var(--border))] bg-[hsl(var(--secondary))] px-14 py-12"
      >
        <svg
          aria-hidden
          className="pointer-events-none absolute -bottom-[120px] -left-[120px]"
          width="500"
          height="500"
          viewBox="0 0 500 500"
          fill="none"
          style={{ opacity: 0.22 }}
        >
          <circle cx="250" cy="250" r="80" stroke="hsl(var(--primary))" strokeWidth="1" />
          <circle
            cx="250"
            cy="250"
            r="140"
            stroke="hsl(var(--primary))"
            strokeWidth="1"
            opacity="0.7"
          />
          <circle
            cx="250"
            cy="250"
            r="200"
            stroke="hsl(var(--primary))"
            strokeWidth="1"
            opacity="0.45"
          />
          <circle
            cx="250"
            cy="250"
            r="260"
            stroke="hsl(var(--primary))"
            strokeWidth="1"
            opacity="0.25"
          />
        </svg>

        <div className="relative">
          <LimberWordmark size={22} />
        </div>

        <div className="relative">
          <span className="limber-eyebrow">Voice triage · office strain</span>
          <h1 className="mt-3 mb-5 max-w-[520px] font-sans text-[64px] font-bold leading-[0.98] tracking-[-0.04em]">
            Less stiff
            <br />
            <span style={{ color: 'hsl(var(--accent))' }}>by Friday.</span>
          </h1>
          <p className="max-w-[420px] text-[16px] leading-[1.55] text-[hsl(var(--muted-foreground))]">
            Five minutes of voice conversation with Brook. You leave with a plan, a clinic, or —
            rarely — an urgent route.
          </p>

          <div
            className="mt-9 flex max-w-[460px] items-start gap-4 rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5"
            style={{ boxShadow: '0 1px 0 hsl(var(--border))' }}
          >
            <BrookAvatar size={48} listening />
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[hsl(var(--muted-foreground))]">
                You&apos;ll be talking to
              </div>
              <div className="mt-1 text-[18px] font-bold text-[hsl(var(--foreground))]">Brook</div>
              <p
                className="mt-2 font-serif text-[15px] italic leading-[1.45]"
                style={{ color: 'hsl(var(--primary-soft-fg))' }}
              >
                &ldquo;I&apos;m calm and quiet. I&apos;ll ask what hurts, then a few follow-ups.
                I&apos;m not a doctor — and I&apos;ll tell you when you need one.&rdquo;
              </p>
            </div>
          </div>
        </div>

        <div className="relative" />
      </aside>

      <div className="relative flex flex-col bg-[hsl(var(--background))] px-14 py-12">
        <div className="flex items-center justify-end gap-3 text-[13px] text-[hsl(var(--muted-foreground))]">
          <ThemeSwitcher />
          <span>
            {isSignup ? 'Already have one? ' : 'New here? '}
            <button
              type="button"
              onClick={() => onModeChange(isSignup ? 'sign-in' : 'sign-up')}
              className="font-semibold text-[hsl(var(--foreground))] hover:underline"
            >
              {isSignup ? 'Sign in' : 'Create an account'}
            </button>
          </span>
        </div>

        <div className="m-auto w-full max-w-[380px]">
          <span className="limber-eyebrow">{isSignup ? 'Create account' : 'Welcome back'}</span>
          <h2 className="mt-2 mb-2 font-sans text-[38px] font-bold leading-[1.05] tracking-[-0.03em]">
            {isSignup ? 'Make a limber account.' : 'Sign in to limber.'}
          </h2>
          <p className="mb-7 text-[14px] leading-[1.5] text-[hsl(var(--muted-foreground))]">
            {isSignup
              ? "We'll set up Brook with a default voice. You can change it later."
              : 'Pick up where you left off. Brook will remember the last topic.'}
          </p>

          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="flex flex-col gap-4">
              <FormField
                control={form.control}
                name="email"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel className="text-[12.5px] font-semibold text-[hsl(var(--foreground))]">
                      Email
                    </FormLabel>
                    <FormControl>
                      <Input
                        type="email"
                        autoComplete="email"
                        placeholder="you@work.com"
                        className="h-11 rounded-xl"
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="password"
                render={({ field }) => (
                  <FormItem>
                    <div className="flex items-baseline justify-between">
                      <FormLabel className="text-[12.5px] font-semibold text-[hsl(var(--foreground))]">
                        Password
                      </FormLabel>
                      {mode === 'sign-in' ? (
                        <span className="text-xs text-[hsl(var(--muted-foreground))]">
                          {/* Forgot-password flow not yet wired; placeholder for future. */}
                          Forgot?
                        </span>
                      ) : null}
                    </div>
                    <div className="relative">
                      <FormControl>
                        <Input
                          type={showPassword ? 'text' : 'password'}
                          autoComplete={mode === 'sign-in' ? 'current-password' : 'new-password'}
                          placeholder={isSignup ? 'At least 8 characters' : '••••••••'}
                          {...field}
                          className="h-11 rounded-xl pr-10"
                        />
                      </FormControl>
                      <button
                        type="button"
                        onClick={onTogglePassword}
                        aria-label={showPassword ? 'Hide password' : 'Show password'}
                        className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
                      >
                        {showPassword ? (
                          <EyeOff className="h-4 w-4" />
                        ) : (
                          <Eye className="h-4 w-4" />
                        )}
                      </button>
                    </div>
                    <FormMessage />
                  </FormItem>
                )}
              />
              {submitError ? (
                <div
                  role="alert"
                  className="rounded-md border border-[hsl(var(--destructive))]/30 bg-[hsl(var(--destructive))]/5 px-3 py-2 text-sm font-medium text-[hsl(var(--destructive))]"
                >
                  {submitError}
                </div>
              ) : null}
              {info ? (
                <div
                  role="status"
                  className="flex gap-2.5 rounded-md border border-[hsl(var(--primary-soft-border))] bg-[hsl(var(--primary-soft))] px-3 py-2.5 text-[13px] leading-snug text-[hsl(var(--primary-soft-fg))]"
                >
                  <Info className="mt-0.5 h-4 w-4 flex-none text-[hsl(var(--primary-soft-fg))]" />
                  <span>{info}</span>
                </div>
              ) : null}
              <Button
                type="submit"
                size="lg"
                className="h-12 w-full rounded-xl bg-[hsl(var(--foreground))] text-[15px] font-semibold text-[hsl(var(--background))] hover:bg-[hsl(var(--foreground))]/90"
                disabled={form.formState.isSubmitting}
              >
                {form.formState.isSubmitting
                  ? 'Working…'
                  : mode === 'sign-in'
                    ? 'Sign in'
                    : 'Create account'}
                <ArrowRight className="ml-1.5 h-4 w-4" style={{ color: 'hsl(var(--accent))' }} />
              </Button>
            </form>
          </Form>

          <p className="mt-7 text-[11.5px] leading-[1.5] text-[hsl(var(--muted-foreground))]">
            By continuing you agree to the{' '}
            <a
              href="#"
              className="text-[hsl(var(--foreground))] underline-offset-2 hover:underline"
            >
              Terms
            </a>{' '}
            and the{' '}
            <a
              href="#"
              className="text-[hsl(var(--foreground))] underline-offset-2 hover:underline"
            >
              Privacy Notice
            </a>
            .
          </p>
        </div>
      </div>
    </div>
  );
}
