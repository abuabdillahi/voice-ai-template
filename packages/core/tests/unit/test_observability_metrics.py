"""Unit tests for `core.observability.handle_metrics_event`.

We avoid importing the LiveKit Agents `MetricsCollectedEvent` itself
so the test stays decoupled from the upstream pydantic schema. Instead
we hand-roll dataclass stand-ins that expose the same attributes the
handler reads (the agent worker passes the real event at runtime; our
handler only needs duck-typed attribute access).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
import structlog
from core.observability import bind, handle_metrics_event, unbind
from structlog.contextvars import clear_contextvars, merge_contextvars
from structlog.testing import LogCapture, capture_logs


@pytest.fixture
def capture_with_contextvars() -> Iterator[LogCapture]:
    """Capture log entries via a real processor chain that includes
    ``merge_contextvars`` — the default ``capture_logs`` short-circuits
    the pipeline so contextvars would be invisible to assertions."""
    cap = LogCapture()
    clear_contextvars()
    structlog.configure(
        processors=[merge_contextvars, cap],
        wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )
    try:
        yield cap
    finally:
        clear_contextvars()
        structlog.reset_defaults()


@dataclass(slots=True)
class _FakeLLMMetrics:
    """Stand-in for `livekit.agents.metrics.LLMMetrics`."""

    type: str = "llm_metrics"
    label: str = "openai-llm"
    request_id: str = "req-1"
    timestamp: float = 1.0
    duration: float = 0.42
    ttft: float = 0.18
    cancelled: bool = False
    completion_tokens: int = 42
    prompt_tokens: int = 7
    prompt_cached_tokens: int = 0
    total_tokens: int = 49
    tokens_per_second: float = 100.0


@dataclass(slots=True)
class _FakeEOUMetrics:
    type: str = "eou_metrics"
    timestamp: float = 2.0
    end_of_utterance_delay: float = 0.31
    transcription_delay: float = 0.12
    on_user_turn_completed_delay: float = 0.04
    speech_id: str = "speech-1"


@dataclass(slots=True)
class _FakeMetricsEvent:
    """Stand-in for `livekit.agents.MetricsCollectedEvent`."""

    metrics: Any
    type: str = "metrics_collected"
    created_at: float = 0.0


def test_handle_metrics_event_emits_turn_metrics_with_numeric_fields() -> None:
    event = _FakeMetricsEvent(metrics=_FakeLLMMetrics())

    with capture_logs() as logs:
        handle_metrics_event(event)

    assert len(logs) == 1
    line = logs[0]

    assert line["event"] == "turn_metrics"
    assert line["log_level"] == "info"
    assert line["metric_type"] == "llm_metrics"
    assert line["label"] == "openai-llm"
    assert line["request_id"] == "req-1"
    assert line["ttft"] == 0.18
    assert line["duration"] == 0.42
    assert line["completion_tokens"] == 42
    assert line["prompt_tokens"] == 7
    assert line["total_tokens"] == 49
    # Booleans must not be projected as numerics.
    assert "cancelled" in line and line["cancelled"] is False


def test_handle_metrics_event_handles_eou_metric_shape() -> None:
    event = _FakeMetricsEvent(metrics=_FakeEOUMetrics())

    with capture_logs() as logs:
        handle_metrics_event(event)

    assert len(logs) == 1
    line = logs[0]

    assert line["event"] == "turn_metrics"
    assert line["metric_type"] == "eou_metrics"
    assert line["end_of_utterance_delay"] == 0.31
    assert line["transcription_delay"] == 0.12
    assert line["on_user_turn_completed_delay"] == 0.04
    assert line["speech_id"] == "speech-1"


def test_handle_metrics_event_includes_bound_contextvars(
    capture_with_contextvars: LogCapture,
) -> None:
    bind(conversation_id="conv-99", session_id="room-abc", user_id="user-7")
    try:
        event = _FakeMetricsEvent(metrics=_FakeLLMMetrics())
        handle_metrics_event(event)
    finally:
        unbind("conversation_id", "session_id", "user_id")

    assert len(capture_with_contextvars.entries) == 1
    line = capture_with_contextvars.entries[0]
    assert line["event"] == "turn_metrics"
    assert line["conversation_id"] == "conv-99"
    assert line["session_id"] == "room-abc"
    assert line["user_id"] == "user-7"


def test_handle_metrics_event_accepts_bare_metrics_object() -> None:
    """If the handler is passed a metrics object directly (no wrapper),
    it should still emit a `turn_metrics` line."""
    with capture_logs() as logs:
        handle_metrics_event(_FakeLLMMetrics())

    assert len(logs) == 1
    assert logs[0]["event"] == "turn_metrics"
    assert logs[0]["metric_type"] == "llm_metrics"


def test_handle_metrics_event_does_not_raise_on_unknown_shape() -> None:
    """A metrics event with no recognised fields should still produce a
    `turn_metrics` line tagged with the runtime class name, not crash."""

    class _Mystery:
        pass

    event = _FakeMetricsEvent(metrics=_Mystery())
    with capture_logs() as logs:
        handle_metrics_event(event)

    assert len(logs) == 1
    assert logs[0]["event"] == "turn_metrics"
    assert logs[0]["metric_type"] == "_Mystery"


def test_capture_logs_uses_structlog_logger() -> None:
    """Sanity check: confirm the module-level logger is a structlog
    logger so `capture_logs` actually intercepts emissions."""
    log = structlog.get_logger("core.observability.metrics")
    with capture_logs() as logs:
        log.info("ping", k=1)
    assert logs == [{"event": "ping", "log_level": "info", "k": 1}]
