"""Unit tests for the contextvars binding seam in `core.observability`.

These exercise the `bind` / `unbind` convenience wrappers and assert
that the bound fields flow through onto emitted log lines via
`structlog`'s `merge_contextvars` processor.

The default ``structlog.testing.capture_logs`` helper short-circuits
the processor chain, so it would not exercise ``merge_contextvars``.
We therefore reconfigure structlog with our own minimal pipeline
(``merge_contextvars`` → ``LogCapture``) for the duration of each
test.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import structlog
from core.observability import bind, unbind
from structlog.contextvars import clear_contextvars, merge_contextvars
from structlog.testing import LogCapture


@pytest.fixture
def capture() -> Iterator[LogCapture]:
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


def test_bound_contextvars_appear_on_emitted_log_lines(capture: LogCapture) -> None:
    bind(conversation_id="conv-1", user_id="user-42")

    log = structlog.get_logger("test")
    log.info("hello", extra=1)

    assert len(capture.entries) == 1
    line = capture.entries[0]
    assert line["event"] == "hello"
    assert line["conversation_id"] == "conv-1"
    assert line["user_id"] == "user-42"
    assert line["extra"] == 1


def test_unbind_removes_keys_from_subsequent_lines(capture: LogCapture) -> None:
    bind(conversation_id="conv-1", user_id="user-42")

    log = structlog.get_logger("test")
    log.info("first")

    unbind("conversation_id", "user_id")
    log.info("second")

    assert capture.entries[0]["conversation_id"] == "conv-1"
    assert capture.entries[0]["user_id"] == "user-42"
    assert "conversation_id" not in capture.entries[1]
    assert "user_id" not in capture.entries[1]
    assert capture.entries[1]["event"] == "second"


def test_bind_with_no_fields_is_a_noop(capture: LogCapture) -> None:
    bind()  # must not raise

    log = structlog.get_logger("test")
    log.info("ping")

    assert capture.entries[0]["event"] == "ping"
    # No extra contextvar keys leaked in.
    assert set(capture.entries[0].keys()) == {"event", "log_level"}


def test_unbind_with_unknown_keys_is_a_noop(capture: LogCapture) -> None:
    unbind("nope")  # must not raise

    bind(only="here")
    unbind("nope", "still-nope", "only")

    log = structlog.get_logger("test")
    log.info("ping")

    assert "only" not in capture.entries[0]
    assert "nope" not in capture.entries[0]
