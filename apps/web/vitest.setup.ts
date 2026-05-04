import '@testing-library/jest-dom/vitest';

// Vite reads these via `import.meta.env`. The component code throws if
// they are missing, so populate dummy values for the test environment.
import.meta.env.VITE_SUPABASE_URL ??= 'http://localhost:54321';
import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY ??= 'test-publishable-key';
import.meta.env.VITE_API_URL ??= 'http://localhost:8000';
