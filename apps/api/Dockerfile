# syntax=docker/dockerfile:1.7

# ---------- Stage 1: builder ----------
# Use the uv-bearing Python image so we get a known-good uv binary
# alongside Python 3.13. We sync the entire workspace because `api`
# depends on the workspace `core` package.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /workspace

# Layer 1: dependency resolution. Copy only the manifests so this layer
# caches whenever the lockfile and pyproject files are unchanged.
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/agent/pyproject.toml apps/agent/pyproject.toml
COPY packages/core/pyproject.toml packages/core/pyproject.toml

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Layer 2: install the workspace itself.
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

# Non-root user.
RUN groupadd --system --gid 1000 appuser \
 && useradd  --system --uid 1000 --gid appuser --create-home appuser

WORKDIR /workspace

COPY --from=builder --chown=appuser:appuser /workspace /workspace

USER appuser

EXPOSE 8000

# Use a python one-liner to avoid pulling curl into the slim runtime.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
