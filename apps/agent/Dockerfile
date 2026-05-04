# syntax=docker/dockerfile:1.7

# ---------- Stage 1: builder ----------
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /workspace

COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/agent/pyproject.toml apps/agent/pyproject.toml
COPY packages/core/pyproject.toml packages/core/pyproject.toml

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY apps/api apps/api
COPY apps/agent apps/agent
COPY packages/core packages/core

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---------- Stage 2: runtime ----------
FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/workspace/.venv/bin:$PATH"

RUN groupadd --system --gid 1000 appuser \
 && useradd  --system --uid 1000 --gid appuser --create-home appuser

WORKDIR /workspace

COPY --from=builder --chown=appuser:appuser /workspace /workspace

USER appuser

# Agent dials out to LiveKit; no inbound port to expose.
CMD ["python", "-m", "agent"]
