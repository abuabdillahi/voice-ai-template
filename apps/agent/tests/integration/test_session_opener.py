"""Integration-style tests for the proactive opener.

Issue 01 — the realtime model used to wait for the user to speak
before producing audio, even though the system prompt instructs it to
open every conversation with a scripted self-introduction. The agent
worker now kicks off an assistant turn immediately after the session
is set up so the user hears the opener within the natural startup
window.

The 1.5.x LiveKit Agents test harness for end-to-end voice-loop
scripting is still flagged as evals-tier (see :mod:`test_session_tools`
for the rationale). Per the established escape hatch, this test asserts
the *contract* the harness would otherwise verify by driving the
``_kick_off_opener`` helper against a tiny fake session and verifying
that the agent worker triggers an assistant turn with no user input
and no second source of truth for the greeting copy.
"""

from __future__ import annotations

from typing import Any

import pytest


class _FakeSession:
    """Captures ``generate_reply`` invocations made by the opener helper."""

    def __init__(self) -> None:
        self.generate_reply_calls: list[dict[str, Any]] = []

    async def generate_reply(self, **kwargs: Any) -> None:
        self.generate_reply_calls.append(kwargs)


@pytest.mark.asyncio
async def test_kick_off_opener_triggers_an_assistant_turn() -> None:
    from agent.session import _kick_off_opener

    session = _FakeSession()

    await _kick_off_opener(session)

    assert len(session.generate_reply_calls) == 1, (
        "the opener helper must trigger exactly one assistant turn; "
        f"got {session.generate_reply_calls}"
    )


@pytest.mark.asyncio
async def test_kick_off_opener_does_not_pass_a_greeting_string() -> None:
    """The opener variant must come from the system prompt, not the agent code.

    AC: "The opener variant is driven entirely by the system prompt's
    existing branching rules — no second source of truth for the
    greeting copy is introduced in the agent code." Concretely, the
    helper must not pass an ``instructions`` or ``user_input`` kwarg
    to ``generate_reply`` — those would re-introduce greeting copy in
    the agent worker.
    """
    from agent.session import _kick_off_opener

    session = _FakeSession()

    await _kick_off_opener(session)

    call_kwargs = session.generate_reply_calls[0]
    assert "instructions" not in call_kwargs, (
        "the opener helper must not pass `instructions` — that would "
        "duplicate the greeting copy alongside the system prompt"
    )
    assert "user_input" not in call_kwargs, (
        "the opener helper must not pass `user_input` — there is no "
        "user input yet at session start"
    )
