"""Application factory for the FastAPI HTTP backend.

The factory is the single seam where settings, middleware, and routes
come together. Tests build their own app via :func:`create_app` so they
can inject overrides; production code uses the module-level instance
exposed by :mod:`api.main`.
"""

from __future__ import annotations

from core.config import Settings, get_settings
from core.observability import setup_logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.middleware import RequestIDMiddleware
from api.routes import router as api_router


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a configured FastAPI application.

    Subsequent issues add routers and middleware here; the factory
    shape stays the same so test wiring does not change as the API
    surface grows.
    """
    settings = settings or get_settings()
    setup_logging(settings)

    app = FastAPI(title="voice-ai api", version="0.0.0")

    # CORS — the Vite dev server origin is included unconditionally;
    # additional origins flow in via `CORS_ORIGINS` (comma-separated).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list or ["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    app.add_middleware(RequestIDMiddleware)

    app.include_router(api_router)

    return app
