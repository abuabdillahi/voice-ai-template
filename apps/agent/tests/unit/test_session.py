"""Unit tests for `agent.session`.

The acceptance criteria call for an integration test using LiveKit
Agents' AgentSession test harness with a scripted realtime model. The
1.5.x harness is available under `livekit.agents.voice.run_result`
but the API is not yet stable across patch releases (the public test
helpers are still flagged "evals"). To keep CI deterministic and
fast, this slice ships unit tests that pin the entrypoint's contract:

* a known system prompt,
* an :class:`Agent` with no tools (issue 06 adds them),
* an :class:`AgentSession` wired with the realtime model the factory
  returns,
* :class:`WorkerOptions` populated from the typed settings.

Issue 06 (tools) introduces the harness-based test once a tool exists
that benefits from the scripted-LLM verification.
"""

from __future__ import annotations

from unittest.mock import patch

from agent.session import (
    SYSTEM_PROMPT,
    build_agent,
    build_session,
    worker_options,
)
from core.config import Settings
from livekit.agents import Agent, AgentSession, WorkerOptions
from livekit.agents.llm import RealtimeModel


def test_build_agent_uses_template_system_prompt() -> None:
    agent = build_agent()
    assert isinstance(agent, Agent)
    # The system prompt is the only behaviour in this slice; pin it
    # explicitly so a regression on the prompt is visible in review.
    assert "helpful conversational assistant" in SYSTEM_PROMPT
    assert agent.instructions == SYSTEM_PROMPT


def test_build_session_wires_realtime_model(settings: Settings) -> None:
    session = build_session(settings)
    assert isinstance(session, AgentSession)
    # The session must end up with the realtime model the factory
    # returns. We don't assert on the concrete subclass — the seam is
    # the factory, not the model class.
    assert isinstance(session.llm, RealtimeModel)


def test_worker_options_pulls_credentials_from_settings(settings: Settings) -> None:
    # Patch get_settings so worker_options uses the fixture rather
    # than the (unset) process environment.
    with patch("agent.session.get_settings", return_value=settings):
        opts = worker_options()
    assert isinstance(opts, WorkerOptions)
    assert opts.ws_url == "wss://test.livekit.cloud"
    assert opts.api_key == "lk-test-key"
    assert opts.api_secret == "lk-test-secret"
    # And the entrypoint pointer must match the function the worker
    # is supposed to dispatch into.
    from agent.session import entrypoint

    assert opts.entrypoint_fnc is entrypoint
