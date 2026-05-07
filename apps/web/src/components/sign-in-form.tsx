import { useCallback, useState, useSyncExternalStore } from 'react';
import { useForm, type UseFormReturn } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { ArrowRight, Eye, EyeOff, Info, Shield } from 'lucide-react';

import { supabase } from '@/lib/supabase';
import { SarjyLogo, SarjyWordmark } from '@/components/sarjy-logo';
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
 * Auth surface. Renders a two-pane desktop layout on `lg` and above and
 * a phone-shaped single-column layout below it. Both views share one
 * :func:`useForm` instance so the input state, submit, and error
 * surfaces stay coherent across resize.
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
// Mobile layout — single column, hero on top, underline tabs, trust footer.
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
    <div className="sarjy-hero-bg flex min-h-screen flex-col">
      {/* Top bar: brand only */}
      <header className="flex items-center justify-between px-5 pt-4 pb-3">
        <SarjyLogo size={22} />
      </header>

      {/* Hero */}
      <div className="px-6 pt-3">
        <span className="sarjy-eyebrow text-[hsl(var(--primary-soft-fg))]">
          Voice triage · office strain
        </span>
        <h1 className="mt-2 mb-2 font-serif text-[34px] leading-[1.15] tracking-[-0.015em]">
          {isSignup ? 'Start a quiet conversation.' : 'Welcome back.'}
          <br />
          <span className="italic text-[hsl(var(--foreground)/0.78)]">
            {isSignup ? 'Talk through the ache.' : 'Pick up where you left off.'}
          </span>
        </h1>
        <p className="text-[13.5px] leading-[1.55] text-[hsl(var(--muted-foreground))]">
          A voice assistant for office-strain symptoms — wrist, eye, neck, back, headaches.
        </p>
      </div>

      {/* Mode tabs (underline) */}
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
                  ? 'border-[hsl(var(--primary))] text-[hsl(var(--foreground))]'
                  : 'border-transparent text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]',
              )}
            >
              {t.label}
            </button>
          );
        })}
      </div>

      {/* Form */}
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
                <FormLabel className="text-[12px] font-semibold text-[hsl(var(--muted-foreground))]">
                  Email
                </FormLabel>
                <FormControl>
                  <Input
                    type="email"
                    autoComplete="email"
                    placeholder="you@example.com"
                    className="h-11 text-[15px]"
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
                  <FormLabel className="text-[12px] font-semibold text-[hsl(var(--muted-foreground))]">
                    Password
                  </FormLabel>
                  {!isSignup ? (
                    <span className="text-[11.5px] text-[hsl(var(--primary-soft-fg))]">
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
                      className="h-11 pr-11 text-[15px]"
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
                {isSignup ? (
                  <p className="text-[11px] text-[hsl(var(--muted-foreground))]">
                    We&apos;ll send a verification link to confirm your email.
                  </p>
                ) : null}
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
            className="mt-1 h-12 w-full text-[14.5px]"
            disabled={form.formState.isSubmitting}
          >
            {form.formState.isSubmitting ? 'Working…' : isSignup ? 'Create account' : 'Sign in'}
            <ArrowRight className="ml-1.5 h-4 w-4" />
          </Button>

          {/* Trust footer pinned to bottom */}
          <div className="mt-auto flex items-center gap-1.5 pt-4 text-[11.5px] text-[hsl(var(--muted-foreground))]">
            <Shield className="h-3.5 w-3.5 flex-none" />
            <span>Sarjy is not a doctor. For emergencies, call your local emergency number.</span>
          </div>
        </form>
      </Form>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Desktop layout — two-pane: marketing aside on the left, form on the right.
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
  return (
    <div className="sarjy-hero-bg grid min-h-screen w-full grid-cols-[1.1fr_1fr]">
      <aside
        aria-label="About Sarjy"
        className="flex flex-col gap-14 border-r border-[hsl(var(--border))] px-14 py-12"
      >
        <SarjyWordmark size={28} />
        <div className="my-auto">
          <span className="sarjy-eyebrow text-[hsl(var(--primary-soft-fg))]">
            Voice-first · office strain
          </span>
          <h1 className="mt-3 mb-4 max-w-[520px] font-serif text-[40px] leading-[1.15] tracking-[-0.015em] sm:text-[52px]">
            Talk through the ache.
            <br />
            <span className="italic text-[hsl(var(--foreground)/0.78)]">
              I&apos;ll help you decide what&apos;s next.
            </span>
          </h1>
          <p className="mb-7 max-w-[440px] text-[15px] leading-[1.55] text-[hsl(var(--muted-foreground))] sm:text-base">
            Sarjy is a voice triage assistant for the five most common office-strain patterns —
            wrist, eyes, neck, back, headache. A few minutes of conversation and you leave with a
            self-care plan or a clinician.
          </p>
          <div className="flex flex-wrap gap-x-6 gap-y-2 text-[13px] text-[hsl(var(--muted-foreground))]">
            <span className="inline-flex items-center gap-1.5">
              <Shield className="h-3.5 w-3.5" /> Sarjy is not a doctor. For emergencies, call your
              local emergency number.
            </span>
          </div>
        </div>
      </aside>

      <div className="relative flex items-center justify-center px-14 py-12">
        <div className="absolute right-6 top-6">
          <ThemeSwitcher />
        </div>
        <div className="w-full max-w-[380px]">
          <div
            role="tablist"
            aria-label="Auth mode"
            className="mb-6 grid grid-cols-2 gap-1 rounded-[10px] bg-[hsl(var(--muted))] p-1"
          >
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
                    'h-9 rounded-md px-3 text-sm transition-colors',
                    active
                      ? 'bg-[hsl(var(--card))] font-semibold text-[hsl(var(--foreground))] shadow-sm'
                      : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]',
                  )}
                >
                  {t.label}
                </button>
              );
            })}
          </div>

          <h2 className="mb-1.5 text-xl font-semibold tracking-tight">
            {mode === 'sign-in' ? 'Welcome back.' : 'Create your account.'}
          </h2>
          <p className="mb-6 text-[13.5px] text-[hsl(var(--muted-foreground))]">
            {mode === 'sign-in'
              ? 'Enter your email to continue.'
              : "Email and a password. We'll send a verification link."}
          </p>

          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="flex flex-col gap-4">
              <FormField
                control={form.control}
                name="email"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Email</FormLabel>
                    <FormControl>
                      <Input
                        type="email"
                        autoComplete="email"
                        placeholder="you@example.com"
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
                      <FormLabel>Password</FormLabel>
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
                          {...field}
                          className="pr-10"
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
                className="w-full"
                disabled={form.formState.isSubmitting}
              >
                {form.formState.isSubmitting
                  ? 'Working…'
                  : mode === 'sign-in'
                    ? 'Sign in'
                    : 'Create account'}
                <ArrowRight className="ml-1.5 h-4 w-4" />
              </Button>
            </form>
          </Form>
        </div>
      </div>
    </div>
  );
}
