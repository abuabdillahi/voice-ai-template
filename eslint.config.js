// Flat ESLint config for the monorepo.
//
// Real TypeScript / React source lands in subsequent issues; this config is
// intentionally permissive enough to run cleanly on a tree with no .ts/.tsx
// files yet, while already wiring the canonical plugin set so future code
// is linted from its first commit.

import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import react from 'eslint-plugin-react';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';

export default [
  {
    ignores: [
      '**/node_modules/**',
      '**/.pnpm-store/**',
      '**/.turbo/**',
      '**/dist/**',
      '**/build/**',
      '**/out/**',
      '**/.next/**',
      '**/.venv/**',
      '**/.uv-cache/**',
      '**/.mypy_cache/**',
      '**/.ruff_cache/**',
      '**/.pytest_cache/**',
      '**/coverage/**',
      'pnpm-lock.yaml',
      'uv.lock',
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['**/*.{ts,tsx,jsx}'],
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.node,
      },
    },
    plugins: {
      react,
      'react-hooks': reactHooks,
    },
    settings: {
      react: { version: 'detect' },
    },
    rules: {
      ...react.configs.recommended.rules,
      ...reactHooks.configs.recommended.rules,
      'react/react-in-jsx-scope': 'off',
      'react/prop-types': 'off',
    },
  },
  {
    files: ['**/*.{js,mjs,cjs}'],
    languageOptions: {
      globals: {
        ...globals.node,
      },
    },
  },
];
