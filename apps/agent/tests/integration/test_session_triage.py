"""Integration-style tests for the OPQRST slot-forwarding hook.

The 1.5.x LiveKit Agents test harness for end-to-end voice-loop
scripting is still flagged as an evals tool and brittle across patch
releases (see ``test_session_tools``). Per the established escape
hatch, this test asserts the *contract* the harness would otherwise
verify:

* ``record_symptom`` runs through the dispatch path the LiveKit
  ``function_tool`` wrapper uses and writes into the in-process slot
  store keyed by ``session_id``,
* ``_emit_triage_state`` reads the snapshot from
  :func:`core.triage.get_state` and pushes it on the
  ``lk.triage-state`` topic,
* the data-channel topic constants are distinct from the existing
  transcription and tool-call topics.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
import structlog
from agent.session import (
    TOOL_CALLS_TOPIC,
    TRIAGE_STATE_TOPIC,
    _emit_triage_state,
    _SessionDeps,
)
from core import triage
from core.auth import User
from core.tools import dispatch
from core.tools.registry import ToolContext


@pytest.fixture(autouse=True)
def _isolate_state() -> Iterator[None]:
    triage._STATES.clear()  # noqa: SLF001
    yield
    triage._STATES.clear()  # noqa: SLF001


def _deps(session_id: str = "user-abc") -> _SessionDeps:
    return _SessionDeps(
        user=User(id=UUID("11111111-1111-1111-1111-111111111111"), email="alice@example.com"),
        log=structlog.get_logger("test"),
        session_id=session_id,
    )


def test_triage_state_topic_is_distinct_from_other_topics() -> None:
    assert TRIAGE_STATE_TOPIC == "lk.triage-state"
    assert TRIAGE_STATE_TOPIC != TOOL_CALLS_TOPIC
    assert TRIAGE_STATE_TOPIC != "lk.transcription"


@pytest.mark.asyncio
async def test_record_symptom_dispatch_writes_through_to_slot_store() -> None:
    deps = _deps()
    ctx = ToolContext(
        user=deps.user,
        log=deps.log,
        session_id=deps.session_id,
    )
    result = await dispatch(
        "record_symptom",
        {"slot": "location", "value": "right wrist"},
        ctx,
    )
    assert isinstance(result, str)
    payload = json.loads(result)
    assert payload["state"] == {"location": "right wrist"}
    assert triage.get_state("user-abc") == {"location": "right wrist"}


@pytest.mark.asyncio
async def test_emit_triage_state_pushes_snapshot_on_lk_triage_state_topic() -> None:
    deps = _deps()
    triage.record_symptom(deps.session_id, "location", "right wrist")
    triage.record_symptom(deps.session_id, "onset", "last week")

    send_text = AsyncMock()
    job_ctx = MagicMock()
    job_ctx.room.local_participant.send_text = send_text

    await _emit_triage_state(job_ctx, deps, deps.log)

    assert send_text.await_count == 1
    payload_arg, kwargs = send_text.await_args.args, send_text.await_args.kwargs
    body = json.loads(payload_arg[0])
    assert kwargs.get("topic") == TRIAGE_STATE_TOPIC
    assert body == {
        "slots": {"location": "right wrist", "onset": "last week"},
        "session_id": "user-abc",
    }


@pytest.mark.asyncio
async def test_emit_triage_state_skips_when_session_id_is_missing() -> None:
    deps = _deps(session_id="")
    send_text = AsyncMock()
    job_ctx = MagicMock()
    job_ctx.room.local_participant.send_text = send_text

    await _emit_triage_state(job_ctx, deps, deps.log)

    assert send_text.await_count == 0


@pytest.mark.asyncio
async def test_emit_triage_state_swallows_send_errors() -> None:
    deps = _deps()
    triage.record_symptom(deps.session_id, "location", "wrist")

    async def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("transport down")

    job_ctx = MagicMock()
    job_ctx.room.local_participant.send_text = _boom

    # Must not raise — best-effort forward.
    await _emit_triage_state(job_ctx, deps, deps.log)
