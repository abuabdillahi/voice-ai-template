import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';

import { supabase } from '@/lib/supabase';
import { SarjyLogo } from '@/components/sarjy-logo';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';

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

/**
 * The shadcn-styled email/password form used by the `/sign-in` route.
 *
 * Lives in `components/` rather than the route file so the test suite
 * can mount it without the TanStack Router runtime. The route file is
 * a thin wrapper around this component.
 */
export function SignInForm({ onSignedIn }: SignInFormProps) {
  const [mode, setMode] = useState<Mode>('sign-in');
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

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
      setInfo('Account created. Check your inbox if email confirmation is enabled, then sign in.');
      setMode('sign-in');
    }
  }

  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <div className="mb-2 flex items-center gap-2">
          <SarjyLogo size={32} />
          <span className="text-base font-semibold">Sarjy</span>
        </div>
        <CardTitle>{mode === 'sign-in' ? 'Sign in' : 'Create account'}</CardTitle>
        <CardDescription>
          {mode === 'sign-in'
            ? 'Enter your email and password to continue.'
            : 'Sign up with email and password.'}
        </CardDescription>
      </CardHeader>
      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} noValidate>
          <CardContent className="space-y-4">
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
                  <FormLabel>Password</FormLabel>
                  <FormControl>
                    <Input
                      type="password"
                      autoComplete={mode === 'sign-in' ? 'current-password' : 'new-password'}
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            {submitError ? (
              <p role="alert" className="text-sm font-medium text-[hsl(var(--destructive))]">
                {submitError}
              </p>
            ) : null}
            {info ? (
              <p role="status" className="text-sm text-[hsl(var(--muted-foreground))]">
                {info}
              </p>
            ) : null}
          </CardContent>
          <CardFooter className="flex flex-col gap-2">
            <Button type="submit" className="w-full" disabled={form.formState.isSubmitting}>
              {form.formState.isSubmitting
                ? 'Working…'
                : mode === 'sign-in'
                  ? 'Sign in'
                  : 'Create account'}
            </Button>
            <Button
              type="button"
              variant="link"
              onClick={() => {
                setSubmitError(null);
                setInfo(null);
                setMode((m) => (m === 'sign-in' ? 'sign-up' : 'sign-in'));
              }}
            >
              {mode === 'sign-in'
                ? "Don't have an account? Sign up"
                : 'Already have an account? Sign in'}
            </Button>
          </CardFooter>
        </form>
      </Form>
    </Card>
  );
}
