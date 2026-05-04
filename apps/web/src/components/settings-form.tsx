import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useQuery } from '@tanstack/react-query';
import { z } from 'zod';

import { apiFetch } from '@/lib/api';
import { supabase } from '@/lib/supabase';
import { VOICE_OPTIONS, type VoiceId, isVoiceId } from '@/lib/voice-options';
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

interface PreferencesResponse {
  preferences: Record<string, unknown>;
}

/**
 * Schema for the settings form.
 *
 * `voice` is constrained to the runtime catalogue from
 * `voice-options.ts`; `preferred_name` mirrors the core validator
 * (1–80 chars, trimmed). Both rules are duplicated server-side in
 * `core.preferences.validate_preference` so client tampering cannot
 * sneak past the API.
 */
const settingsSchema = z.object({
  preferredName: z
    .string()
    .max(80, { message: 'Preferred name must be 80 characters or fewer.' })
    .default(''),
  voice: z.enum(VOICE_OPTIONS).optional(),
});

type SettingsValues = z.infer<typeof settingsSchema>;

export interface SettingsFormProps {
  /** Called after a successful sign-out. Tests use this to assert the redirect. */
  onSignedOut?: () => void;
}

/**
 * Settings form: preferred name + voice + sign-out.
 *
 * Lives in `components/` rather than the route file so the test suite
 * can mount it without the TanStack Router runtime. The route file is
 * a thin wrapper around this component (see `routes/settings.tsx`).
 *
 * Save behaviour: the form issues one `PUT /preferences/{key}` per
 * *changed* field. A field that matches the server-loaded value is
 * skipped — this keeps the wire payload small and the per-request
 * validation surface narrow.
 */
export function SettingsForm({ onSignedOut }: SettingsFormProps) {
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ['preferences'],
    queryFn: () => apiFetch<PreferencesResponse>('/preferences'),
    staleTime: 5_000,
  });

  const form = useForm<SettingsValues>({
    resolver: zodResolver(settingsSchema),
    defaultValues: { preferredName: '', voice: undefined },
  });

  // Once the GET returns, seed the form with the user's currently-
  // stored values. Without this, a save that did not touch a field
  // would PUT an empty string and clobber the server value.
  useEffect(() => {
    if (!data) return;
    const stored = data.preferences;
    const name = typeof stored.preferred_name === 'string' ? stored.preferred_name : '';
    const voice = isVoiceId(stored.voice) ? (stored.voice as VoiceId) : undefined;
    form.reset({ preferredName: name, voice });
  }, [data, form]);

  async function onSubmit(values: SettingsValues) {
    setSubmitError(null);
    setInfo(null);

    const stored = data?.preferences ?? {};
    const previousName = typeof stored.preferred_name === 'string' ? stored.preferred_name : '';
    const previousVoice = isVoiceId(stored.voice) ? stored.voice : undefined;

    const writes: Promise<unknown>[] = [];
    const trimmedName = values.preferredName?.trim() ?? '';
    if (trimmedName && trimmedName !== previousName) {
      writes.push(
        apiFetch('/preferences/preferred_name', {
          method: 'PUT',
          body: { value: trimmedName },
        }),
      );
    }
    if (values.voice && values.voice !== previousVoice) {
      writes.push(
        apiFetch('/preferences/voice', {
          method: 'PUT',
          body: { value: values.voice },
        }),
      );
    }

    if (writes.length === 0) {
      setInfo('No changes to save.');
      return;
    }

    try {
      await Promise.all(writes);
      setInfo('Saved.');
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : 'Save failed.');
    }
  }

  async function onSignOut() {
    await supabase.auth.signOut();
    onSignedOut?.();
  }

  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle>Settings</CardTitle>
        <CardDescription>
          Tell the assistant what to call you and pick a voice. Changes apply on the next
          conversation.
        </CardDescription>
      </CardHeader>
      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} noValidate>
          <CardContent className="space-y-4">
            <FormField
              control={form.control}
              name="preferredName"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Preferred name</FormLabel>
                  <FormControl>
                    <Input
                      type="text"
                      autoComplete="given-name"
                      placeholder="e.g. Sam"
                      disabled={isLoading}
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="voice"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Voice</FormLabel>
                  <Select
                    value={field.value ?? ''}
                    onValueChange={(v) => field.onChange(v as VoiceId)}
                    disabled={isLoading}
                  >
                    <FormControl>
                      <SelectTrigger aria-label="Voice">
                        <SelectValue placeholder="Pick a voice" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {VOICE_OPTIONS.map((voice) => (
                        <SelectItem key={voice} value={voice}>
                          {voice}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
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
              {form.formState.isSubmitting ? 'Saving…' : 'Save'}
            </Button>
            <Button type="button" variant="outline" className="w-full" onClick={onSignOut}>
              Sign out
            </Button>
          </CardFooter>
        </form>
      </Form>
    </Card>
  );
}
