import { supabase } from './supabase';

const DEFAULT_BASE = 'http://localhost:8000';

/** Thrown by `apiFetch` when the response is not 2xx. */
export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}

interface ApiFetchOptions extends Omit<RequestInit, 'body'> {
  body?: unknown;
}

/**
 * Typed fetch wrapper that:
 *
 * 1. Prepends `VITE_API_URL` (default `http://localhost:8000`).
 * 2. Attaches the Supabase access token as a Bearer header when present.
 * 3. JSON-encodes the body and sets `Content-Type` automatically.
 * 4. Parses the JSON response on success and raises `ApiError` on failure.
 */
export async function apiFetch<T>(path: string, options: ApiFetchOptions = {}): Promise<T> {
  const baseURL = import.meta.env.VITE_API_URL ?? DEFAULT_BASE;

  const { data: sessionData } = await supabase.auth.getSession();
  const accessToken = sessionData.session?.access_token;

  const headers = new Headers(options.headers);
  headers.set('Accept', 'application/json');
  if (accessToken) {
    headers.set('Authorization', `Bearer ${accessToken}`);
  }

  const { body: rawBody, ...rest } = options;
  const init: RequestInit = { ...rest, headers };
  if (rawBody !== undefined && rawBody !== null) {
    headers.set('Content-Type', 'application/json');
    init.body = JSON.stringify(rawBody);
  }

  const url = `${baseURL.replace(/\/$/, '')}${path.startsWith('/') ? path : `/${path}`}`;
  const response = await fetch(url, init);

  const contentType = response.headers.get('content-type') ?? '';
  const payload = contentType.includes('application/json')
    ? await response.json().catch(() => undefined)
    : await response.text().catch(() => undefined);

  if (!response.ok) {
    throw new ApiError(response.status, `${response.status} ${response.statusText}`, payload);
  }

  return payload as T;
}
