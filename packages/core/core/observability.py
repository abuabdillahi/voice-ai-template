"""Structured logging configuration shared by every adapter.

`setup_logging` is idempotent and may be called from any process entry
point (the API factory, the agent worker, tests). It configures
`structlog` to render JSON in production and a developer-friendly
console renderer otherwise.

The module also exposes context-vars for the per-request correlation
identifier (`request_id`) and the resolved end-user id (`user_id`).
Middleware binds these for the duration of a request; emitting code
never imports them directly — it just calls
``structlog.get_logger().info(...)`` and the bound context flows
through.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import structlog
from structlog.contextvars import (
    bind_contextvars,
    clear_contextvars,
    merge_contextvars,
    unbind_contextvars,
)
from structlog.types import Processor

from core.config import Settings, get_settings

_CONFIGURED = False


def setup_logging(settings: Settings | None = None) -> None:
    """Configure stdlib logging and structlog. Safe to call repeatedly."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    settings = settings or get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
        force=True,
    )

    is_dev = settings.environment.lower() in {"development", "dev", "local"}

    shared_processors: list[Processor] = [
        merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer: Processor
    renderer = structlog.dev.ConsoleRenderer() if is_dev else structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    _CONFIGURED = True


def bind_request_context(
    *, request_id: str | None = None, user_id: str | None = None, **extra: Any
) -> None:
    """Bind correlation identifiers to the current logging context."""
    payload: dict[str, Any] = dict(extra)
    if request_id is not None:
        payload["request_id"] = request_id
    if user_id is not None:
        payload["user_id"] = user_id
    if payload:
        bind_contextvars(**payload)


def clear_request_context() -> None:
    """Remove all context-vars previously bound for the current task."""
    clear_contextvars()


@contextmanager
def request_context(
    *, request_id: str | None = None, user_id: str | None = None, **extra: Any
) -> Iterator[None]:
    """Scoped binding helper for code paths that don't sit behind middleware."""
    keys: list[str] = []
    if request_id is not None:
        keys.append("request_id")
    if user_id is not None:
        keys.append("user_id")
    keys.extend(extra.keys())
    bind_request_context(request_id=request_id, user_id=user_id, **extra)
    try:
        yield
    finally:
        if keys:
            unbind_contextvars(*keys)


__all__ = [
    "bind_request_context",
    "clear_request_context",
    "request_context",
    "setup_logging",
]
