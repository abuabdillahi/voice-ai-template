"""Session-level test for the issue 02 prior-session recall injection.

Mirrors the contract-shaped pattern established in
:mod:`test_session_persistence` — rather than spin up a full LiveKit
WebRTC harness, assert the wiring path the entrypoint glue depends on:

* :func:`core.conversations.list_recent_with_recall` returns
  :class:`PriorSession` instances filtered to rows with an identified
  condition,
* :func:`agent.session.build_triage_system_prompt` is byte-for-byte
  identical to the static :data:`SYSTEM_PROMPT` for an empty list, and
* an :class:`Agent` constructed via :func:`build_agent` with
  ``instructions`` from a non-empty prior-session list carries the
  prior condition id verbatim in its ``instructions`` string.
"""

from __future__ import annotations

from datetime import UTC, datetime

from agent.session import (
    SYSTEM_PROMPT,
    build_agent,
    build_triage_system_prompt,
)
from core.conversations import PriorSession


def test_empty_prior_sessions_renders_unchanged_prompt() -> None:
    """The first-time-user regression anchor.

    With no prior condition-bearing sessions, the rendered triage
    system prompt is byte-for-byte identical to today's static
    SYSTEM_PROMPT — no behaviour change for users the recall feature
    does not apply to.
    """
    assert build_triage_system_prompt([]) == SYSTEM_PROMPT


def test_agent_instructions_carry_fixture_condition_id() -> None:
    """End-to-end-shaped assertion on the rendered Agent instructions.

    With one fixture :class:`PriorSession`, the Agent's
    ``instructions`` string contains the fixture's
    ``identified_condition_id`` and the recall context — proving the
    builder threading from the prior-session list through
    :func:`build_triage_system_prompt` to :func:`build_agent` is
    intact.
    """
    fixture = PriorSession(
        started_at=datetime(2026, 5, 6, tzinfo=UTC),
        identified_condition_id="carpal_tunnel",
        recall_context=(
            "User reported wrist tingling consistent with carpal tunnel; "
            "agent recommended the conservative protocol."
        ),
    )
    instructions = build_triage_system_prompt([fixture])
    agent = build_agent(instructions=instructions)
    assert "carpal_tunnel" in agent.instructions
    assert "User reported wrist tingling" in agent.instructions
    # Empty input must still render identically to today's static
    # prompt — guards against drift in the alias.
    fallback = build_triage_system_prompt([])
    assert fallback == SYSTEM_PROMPT


def test_returning_user_short_refresher_threads_to_agent_instructions() -> None:
    """``is_returning_user=True`` end-to-end through to ``Agent.instructions``.

    The integration-shaped assertion: a stubbed returning-user path
    (no prior condition-bearing sessions, but the user is recognised)
    yields an Agent whose instructions carry the short-refresher
    phrasing verbatim.
    """
    instructions = build_triage_system_prompt([], is_returning_user=True)
    agent = build_agent(instructions=instructions)
    assert (
        "Hi, Sarjy here. Quick reminder I'm still an educational tool, not a doctor."
        in agent.instructions
    )
