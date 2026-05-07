import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

// Mock the Supabase client. The real `@supabase/supabase-js` `createClient`
// performs network setup at construction time; the mock returned here
// covers only the surface the form actually touches. Mocks are hoisted
// above the module imports so the factory closure does not capture
// `undefined` references.
const { signInMock, signUpMock } = vi.hoisted(() => ({
  signInMock: vi.fn(),
  signUpMock: vi.fn(),
}));

vi.mock('@/lib/supabase', () => ({
  supabase: {
    auth: {
      signInWithPassword: signInMock,
      signUp: signUpMock,
    },
  },
}));

import { SignInForm } from '@/components/sign-in-form';

describe('SignInForm', () => {
  beforeEach(() => {
    signInMock.mockReset();
    signUpMock.mockReset();
  });

  it('renders email and password fields', () => {
    render(<SignInForm />);
    expect(screen.getByLabelText(/^email$/i)).toBeInTheDocument();
    // The redesigned form has a "Show password" toggle button that
    // also matches a loose `/password/i` query, so we anchor the
    // regex to the field label exactly.
    expect(screen.getByLabelText(/^password$/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^sign in$/i })).toBeInTheDocument();
  });

  it('shows validation messages for invalid input', async () => {
    const user = userEvent.setup();
    render(<SignInForm />);

    await user.click(screen.getByRole('button', { name: /^sign in$/i }));

    await waitFor(() => {
      expect(screen.getByText(/valid email address/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/password must be at least 8 characters/i)).toBeInTheDocument();
    expect(signInMock).not.toHaveBeenCalled();
  });

  it('submits credentials when the form is valid', async () => {
    signInMock.mockResolvedValue({ error: null });
    const onSignedIn = vi.fn();
    const user = userEvent.setup();
    render(<SignInForm onSignedIn={onSignedIn} />);

    await user.type(screen.getByLabelText(/^email$/i), 'alice@example.com');
    await user.type(screen.getByLabelText(/^password$/i), 'correct-horse');
    await user.click(screen.getByRole('button', { name: /^sign in$/i }));

    await waitFor(() => {
      expect(signInMock).toHaveBeenCalledWith({
        email: 'alice@example.com',
        password: 'correct-horse', // pragma: allowlist secret
      });
    });
    expect(onSignedIn).toHaveBeenCalled();
  });
});
