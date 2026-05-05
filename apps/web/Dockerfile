# syntax=docker/dockerfile:1.7

# ---------- Stage 1: builder ----------
FROM node:22-alpine AS builder

ENV PNPM_HOME=/root/.local/share/pnpm \
    PATH=/root/.local/share/pnpm:$PATH

# Enable pnpm via Corepack so we get the version pinned in package.json.
RUN corepack enable

WORKDIR /workspace

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml turbo.json ./
COPY apps/web/package.json apps/web/package.json
COPY apps/api/package.json apps/api/package.json
COPY apps/agent/package.json apps/agent/package.json
COPY packages/core/package.json packages/core/package.json

RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile

COPY apps/web apps/web

# Vite inlines VITE_* vars into the bundle at build time. Pass them through
# as build args so the static assets ship with the right Supabase project
# and api base URL.
ARG VITE_API_URL
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_PUBLISHABLE_KEY
ENV VITE_API_URL=$VITE_API_URL \
    VITE_SUPABASE_URL=$VITE_SUPABASE_URL \
    VITE_SUPABASE_PUBLISHABLE_KEY=$VITE_SUPABASE_PUBLISHABLE_KEY

# `pnpm gen:api` is not run here — `apps/web/src/api/types.gen.ts` is
# committed and regenerated explicitly via the workspace script.
RUN pnpm --filter @voice-ai/web build

# ---------- Stage 2: runtime ----------
FROM nginx:alpine AS runtime

# Custom config: TLS on 443 via mounted Cloudflare Origin Certificate,
# /api/* reverse-proxied to the api service, SPA fallback for client
# routes. Certs are mounted at /etc/nginx/certs by docker-compose.
COPY apps/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /workspace/apps/web/dist /usr/share/nginx/html

EXPOSE 80 443

CMD ["nginx", "-g", "daemon off;"]
