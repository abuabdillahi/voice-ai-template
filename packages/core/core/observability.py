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

Issue 11 adds the per-turn metrics hook: :func:`handle_metrics_event`
accepts a LiveKit Agents ``MetricsCollectedEvent`` and emits a single
INFO-level log line with the numeric latency and token-count fields
the framework exposes, plus whatever contextvars are currently bound
(``conversation_id``, ``session_id``, ``user_id``). The agent worker
subscribes to ``metrics_collected`` on its ``AgentSession`` and
forwards each event here.
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

# Numeric/scalar fields we surface on the structured `turn_metrics`
# log line. Different LiveKit Agents metric event types (LLM, STT,
# TTS, EOU, RealtimeModel, VAD, Interruption) expose overlapping but
# distinct subsets — we project whatever is present so a single log
# format covers all of them and downstream `grep`/`jq` queries do not
# need to special-case the metric type.
_METRIC_NUMERIC_FIELDS: tuple[str, ...] = (
    # Common
    "duration",
    "timestamp",
    # LLM / RealtimeModel
    "ttft",
    "completion_tokens",
    "prompt_tokens",
    "prompt_cached_tokens",
    "total_tokens",
    "tokens_per_second",
    "input_tokens",
    "output_tokens",
    # STT
    "audio_duration",
    "acquire_time",
    # TTS
    "ttfb",
    "characters_count",
    # EOU — the canonical TTFA sub-metrics
    "end_of_utterance_delay",
    "transcription_delay",
    "on_user_turn_completed_delay",
    # VAD
    "idle_time",
    "inference_duration_total",
    "inference_count",
    # Interruption
    "total_duration",
    "prediction_duration",
    "detection_delay",
    "num_interruptions",
    "num_backchannels",
    "num_requests",
    # RealtimeModel session-level
    "session_duration",
)

# Identity / classification fields we keep alongside the numerics so a
# log reader can correlate a `turn_metrics` line back to its source.
_METRIC_IDENTITY_FIELDS: tuple[str, ...] = (
    "type",
    "label",
    "request_id",
    "speech_id",
    "segment_id",
    "cancelled",
    "streamed",
    "connection_reused",
)

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


def bind(**fields: Any) -> None:
    """Bind arbitrary fields to the current structlog context.

    Thin convenience over :func:`structlog.contextvars.bind_contextvars`
    so callers (request-id middleware, agent session entrypoint,
    conversation persistence) all funnel through one entrypoint and
    `core.observability` stays the single seam for context propagation.
    """
    if fields:
        bind_contextvars(**fields)


def unbind(*keys: str) -> None:
    """Remove the named keys from the current structlog context.

    Thin convenience over :func:`structlog.contextvars.unbind_contextvars`.
    Keys that are not currently bound are silently ignored.
    """
    if keys:
        unbind_contextvars(*keys)


def handle_metrics_event(event: Any) -> None:
    """Emit a structured ``turn_metrics`` log line for a LiveKit metrics event.

    Accepts a LiveKit Agents ``MetricsCollectedEvent`` (which wraps an
    ``AgentMetrics`` union — LLM, STT, TTS, EOU, RealtimeModel, VAD,
    Interruption). Projects the numeric latency and token-count fields
    the framework exposes onto a single INFO-level log line tagged
    ``event = "turn_metrics"``. The currently-bound contextvars
    (``conversation_id``, ``session_id``, ``user_id``, …) flow through
    automatically via the ``merge_contextvars`` processor.

    The function never raises: a malformed or unexpected event shape
    degrades to a warning so a metrics-pipeline bug cannot tear down a
    live voice session.
    """
    log = structlog.get_logger("core.observability.metrics")

    metrics = getattr(event, "metrics", event)
    payload: dict[str, Any] = {}

    for field in _METRIC_IDENTITY_FIELDS:
        value = getattr(metrics, field, None)
        if value is not None:
            payload[field] = value

    for field in _METRIC_NUMERIC_FIELDS:
        value = getattr(metrics, field, None)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        payload[field] = value

    metric_type = payload.pop("type", None) or type(metrics).__name__

    # The first positional arg becomes the structlog ``event`` key in
    # the rendered JSON line, so a `grep "turn_metrics"` is enough to
    # pull every per-turn metric out of the worker's stdout.
    log.info("turn_metrics", metric_type=metric_type, **payload)


__all__ = [
    "bind",
    "bind_request_context",
    "clear_request_context",
    "handle_metrics_event",
    "request_context",
    "setup_logging",
    "unbind",
]
