"""ASGI entry point.

`uvicorn api.main:app` keeps working — the factory lives in
:mod:`api.app` so tests can construct a fresh instance with overrides.
"""

from __future__ import annotations

from api.app import create_app

app = create_app()
