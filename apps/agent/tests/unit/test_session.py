"""Unit tests for `agent.session`.

After the issue-01 triage pivot, this suite pins the contract for the
educational triage system prompt and the scaffolding around it.
``build_system_prompt`` (the personalisation helper) and the example
session/worker wiring tests continue to apply unchanged — the helper is
retained as kept-public-API surface (ADR 0006) but is bypassed by the
triage entrypoint.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

from agent.session import (
    SYSTEM_PROMPT,
    build_agent,
    build_session,
    build_system_prompt,
    build_triage_system_prompt,
    worker_options,
)
from core.config import Settings
from core.conversations import PriorSession
from livekit.agents import Agent, AgentSession, WorkerOptions
from livekit.agents.llm import RealtimeModel


def test_build_agent_uses_triage_system_prompt() -> None:
    agent = build_agent()
    assert isinstance(agent, Agent)
    # Pin the load-bearing framing so a regression on the prompt is
    # visible in review. The full prompt-shape assertions live in
    # `tests/integration/test_session_tools.py`.
    assert "educational triage" in SYSTEM_PROMPT.lower()
    assert "not a doctor" in SYSTEM_PROMPT.lower()
    assert agent.instructions == SYSTEM_PROMPT


def test_build_session_wires_realtime_model(settings: Settings) -> None:
    session = build_session(settings)
    assert isinstance(session, AgentSession)
    # The session must end up with the realtime model the factory
    # returns. We don't assert on the concrete subclass — the seam is
    # the factory, not the model class.
    assert isinstance(session.llm, RealtimeModel)


def test_build_session_attaches_tts_for_safety_say(settings: Settings) -> None:
    """Realtime mode has no TTS pipeline; safety escalations need ``say()``.

    Attaching a TTS to the AgentSession lets the safety hook play the
    versioned escalation script verbatim via ``session.say(script)``
    instead of the brittle ``generate_reply(instructions=...)`` fallback,
    which raced with the realtime model's in-flight reply.
    """
    session = build_session(settings)
    assert session.tts is not None, (
        "AgentSession must have a TTS attached so session.say() works in "
        "realtime mode for safety escalations"
    )


def test_worker_options_pulls_credentials_from_settings(settings: Settings) -> None:
    # Patch get_settings so worker_options uses the fixture rather
    # than the (unset) process environment.
    with patch("agent.session.get_settings", return_value=settings):
        opts = worker_options()
    assert isinstance(opts, WorkerOptions)
    assert opts.ws_url == "wss://test.livekit.cloud"
    assert opts.api_key == "lk-test-key"  # pragma: allowlist secret
    assert opts.api_secret == "lk-test-secret"  # pragma: allowlist secret
    # And the entrypoint pointer must match the function the worker
    # is supposed to dispatch into.
    from agent.session import entrypoint

    assert opts.entrypoint_fnc is entrypoint


# ---------------------------------------------------------------------------
# Issue 10 — preference-driven personalisation
# ---------------------------------------------------------------------------


def test_build_system_prompt_returns_default_without_name() -> None:
    assert build_system_prompt(None) == SYSTEM_PROMPT
    assert build_system_prompt("") == SYSTEM_PROMPT


def test_build_system_prompt_appends_preferred_name() -> None:
    prompt = build_system_prompt("Sam")
    assert prompt.startswith(SYSTEM_PROMPT)
    assert "prefers to be called Sam" in prompt


def test_build_system_prompt_inlines_stored_preferences() -> None:
    """Stored preferences other than name/voice are listed as facts.

    Without this preload the model has to call get_preference to
    recall anything, which it does inconsistently — cross-session
    recall feels broken.
    """
    prompt = build_system_prompt(
        None,
        {"favorite_color": "blue", "preferred_name": "Sam", "voice": "sage"},
    )
    assert "favorite color: blue" in prompt
    # preferred_name and voice are excluded from the facts block —
    # name is handled above; voice is session config, not a fact.
    assert "preferred name: Sam" not in prompt
    assert "voice: sage" not in prompt


def test_build_system_prompt_omits_facts_block_when_no_extra_preferences() -> None:
    prompt = build_system_prompt("Sam", {"preferred_name": "Sam", "voice": "sage"})
    # The SYSTEM_PROMPT mentions "Known facts" in its meta-instructions;
    # we are checking the absence of the appended facts list. The list
    # uses the literal "Known facts about the user (from prior" header.
    assert "Known facts about the user (from prior" not in prompt


def test_build_agent_uses_custom_instructions() -> None:
    agent = build_agent(instructions="custom prompt for the realtime model")
    assert agent.instructions == "custom prompt for the realtime model"


def test_build_session_passes_voice_to_factory(settings: Settings) -> None:
    with patch("agent.session.create_realtime_model") as factory:
        factory.return_value = build_session(settings).llm  # any RealtimeModel
        build_session(settings, voice="sage")
        # The most-recent call should be ours; assert the kwarg shape.
        kwargs = factory.call_args.kwargs
        assert kwargs.get("voice") == "sage"


def test_build_session_passes_same_voice_to_realtime_and_tts(settings: Settings) -> None:
    """Realtime and TTS must use the same voice or escalations sound jarring.

    The realtime model speaks the everyday turns and the TTS speaks the
    safety script. If they use different voices, the safety alert
    sounds like it comes from a different system. Both factories must
    receive the same ``voice`` value.
    """
    real_session = build_session(settings)  # any RealtimeModel + TTS for return value
    with (
        patch("agent.session.create_realtime_model") as rt_factory,
        patch("agent.session.create_safety_tts") as tts_factory,
    ):
        rt_factory.return_value = real_session.llm
        tts_factory.return_value = real_session.tts
        build_session(settings, voice="sage")
        assert rt_factory.call_args.kwargs.get("voice") == "sage"
        assert tts_factory.call_args.kwargs.get("voice") == "sage"


def test_build_session_default_voice_overlaps_both_catalogs(settings: Settings) -> None:
    """The default voice must exist in both realtime and TTS catalogs.

    Realtime-only voices (``marin``, ``cedar``) cannot be used by the
    OpenAI TTS plugin and would error at speak time. The default has
    to come from the overlapping set: alloy, ash, ballad, coral, sage,
    shimmer, verse.
    """
    real_session = build_session(settings)
    with (
        patch("agent.session.create_realtime_model") as rt_factory,
        patch("agent.session.create_safety_tts") as tts_factory,
    ):
        rt_factory.return_value = real_session.llm
        tts_factory.return_value = real_session.tts
        build_session(settings)  # no explicit voice
        rt_voice = rt_factory.call_args.kwargs.get("voice")
        tts_voice = tts_factory.call_args.kwargs.get("voice")
        assert rt_voice == tts_voice, (
            "default voice must be the same on both factories; "
            f"got realtime={rt_voice!r}, tts={tts_voice!r}"
        )
        overlapping = {"alloy", "ash", "ballad", "coral", "sage", "shimmer", "verse"}
        assert rt_voice in overlapping, (
            f"default voice {rt_voice!r} must come from the overlapping set "
            f"that both gpt-realtime and gpt-4o-mini-tts support; got "
            f"none of {overlapping}"
        )


# ---------------------------------------------------------------------------
# Cross-session recall — prompt-time injection of prior-session blocks
# ---------------------------------------------------------------------------


def _prior(condition_id: str, recall: str | None = None, *, day: int = 4) -> PriorSession:
    return PriorSession(
        started_at=datetime(2026, 5, day, tzinfo=UTC),
        identified_condition_id=condition_id,
        recall_context=recall,
    )


def test_build_triage_system_prompt_empty_matches_static_prompt() -> None:
    """Empty input is byte-for-byte identical to the static SYSTEM_PROMPT.

    This is the regression-test anchor for first-time users and for
    returning users whose prior sessions all ended without an
    identified condition.
    """
    assert build_triage_system_prompt([]) == SYSTEM_PROMPT
    assert build_triage_system_prompt(None) == SYSTEM_PROMPT


def test_build_triage_system_prompt_with_one_prior_includes_condition_and_recall() -> None:
    prior = _prior("carpal_tunnel", recall="User reported wrist tingling, gave glides protocol.")
    prompt = build_triage_system_prompt([prior])
    assert "carpal_tunnel" in prompt
    assert "User reported wrist tingling, gave glides protocol." in prompt
    # Static prompt body must be retained — assert via a substring that
    # appears only there.
    assert "educational triage" in prompt.lower()


def test_build_triage_system_prompt_three_prior_includes_both_blocks() -> None:
    sessions = [
        _prior("carpal_tunnel", recall="latest visit recall", day=6),
        _prior("tension_type_headache", recall="middle visit recall", day=5),
        _prior("lumbar_strain", recall="oldest visit recall", day=4),
    ]
    prompt = build_triage_system_prompt(sessions)
    assert "Most recent session" in prompt
    assert "carpal_tunnel" in prompt
    assert "Earlier sessions (for pattern recognition" in prompt
    assert "tension_type_headache" in prompt
    assert "lumbar_strain" in prompt
    # The most-recent block leads; the earlier-sessions block follows.
    assert prompt.index("Most recent session") < prompt.index("Earlier sessions")


def test_build_triage_system_prompt_contains_two_new_rules_verbatim() -> None:
    """The two new triage rules must appear verbatim in the rendered prompt.

    Drift in the wording of either rule is exactly the failure mode
    that re-opens the cross-session hallucination risk the safety
    floor is built to avoid.
    """
    from agent.session import _TRIAGE_NUMBERS_RULE, _TRIAGE_OPENER_RULE

    # Empty input still includes both rules — they are unconditional.
    empty_prompt = build_triage_system_prompt([])
    assert _TRIAGE_OPENER_RULE in empty_prompt
    assert _TRIAGE_NUMBERS_RULE in empty_prompt

    populated = build_triage_system_prompt([_prior("carpal_tunnel", recall="recall blob")])
    assert _TRIAGE_OPENER_RULE in populated
    assert _TRIAGE_NUMBERS_RULE in populated


def test_build_triage_system_prompt_handles_null_recall() -> None:
    """A prior session with NULL recall_context still renders without raising."""
    prompt = build_triage_system_prompt([_prior("upper_trapezius_strain", recall=None)])
    assert "upper_trapezius_strain" in prompt
    assert "(no recall context recorded)" in prompt


# ---------------------------------------------------------------------------
# Sarjy rebrand — agent self-introduction in opening turn
# ---------------------------------------------------------------------------


def test_static_prompt_contains_english_only_rule_in_every_branch() -> None:
    """The English-only rule must appear verbatim in every prompt render.

    The rule lives in the static section so it applies first-time,
    returning, with-priors, and without-priors. Drift in the wording
    re-opens the silent-translation failure mode the rule guards
    against.
    """
    from agent.session import _ENGLISH_ONLY_RULE

    empty = build_triage_system_prompt([])
    populated = build_triage_system_prompt([_prior("carpal_tunnel", recall="recall blob")])

    for prompt in (empty, populated):
        assert _ENGLISH_ONLY_RULE in prompt
        # And the user-facing refusal phrasing is byte-for-byte:
        assert "I can only respond in English — could you repeat that in English?" in prompt


def test_returning_user_no_priors_uses_short_refresher() -> None:
    """``(True, [])`` swaps the full disclaimer for the short refresher.

    The short opener is byte-for-byte: ``Hi, Sarjy here. Quick reminder
    I'm still an educational tool, not a doctor.`` and the static
    "Open every new conversation with this disclaimer" instruction is
    no longer present in this branch.
    """
    short_opener = "Hi, Sarjy here. Quick reminder I'm still an educational tool, not a doctor."
    full_disclaimer_instruction = (
        "Open every new conversation with this disclaimer in your own words"
    )

    prompt = build_triage_system_prompt([], is_returning_user=True)
    assert short_opener in prompt
    assert full_disclaimer_instruction not in prompt

    # First-time branch keeps the full disclaimer instruction and does
    # NOT contain the short refresher phrasing.
    first_time_prompt = build_triage_system_prompt([], is_returning_user=False)
    assert full_disclaimer_instruction in first_time_prompt
    assert short_opener not in first_time_prompt


def test_returning_user_with_priors_composes_refresher_and_recall_block() -> None:
    """``(True, [PriorSession])`` composes the short refresher with the recall block.

    Short refresher leads; the existing "Most recent session" block
    follows so the agent has both the relational anchor and the prior-
    condition context.
    """
    prior = _prior("carpal_tunnel", recall="User reported wrist tingling.")
    prompt = build_triage_system_prompt([prior], is_returning_user=True)

    short_opener = "Hi, Sarjy here. Quick reminder I'm still an educational tool, not a doctor."
    assert short_opener in prompt
    assert "Most recent session" in prompt
    assert "carpal_tunnel" in prompt
    assert "User reported wrist tingling." in prompt
    assert "Open every new conversation with this disclaimer" not in prompt


def test_returning_user_branches_keep_english_only_and_numbers_rules() -> None:
    """Existing safety rules survive the new branching unchanged."""
    from agent.session import _ENGLISH_ONLY_RULE, _TRIAGE_NUMBERS_RULE

    for prompt in (
        build_triage_system_prompt([], is_returning_user=True),
        build_triage_system_prompt(
            [_prior("carpal_tunnel", recall="recall blob")], is_returning_user=True
        ),
    ):
        assert _ENGLISH_ONLY_RULE in prompt
        assert _TRIAGE_NUMBERS_RULE in prompt


def test_static_prompt_instructs_sarjy_self_introduction() -> None:
    """First-time users hear ``Hi, I'm Sarjy.`` immediately before the disclaimer.

    The phrasing is fixed in the prompt rather than left to the model
    so the test suite can assert it verbatim. The rule lives in the
    static section of ``build_triage_system_prompt`` so it applies in
    every render — first-time, returning, with-priors, without-priors.
    """
    empty_prompt = build_triage_system_prompt([])
    assert "Hi, I'm Sarjy." in empty_prompt
    assert "before the educational-tool disclaimer" in empty_prompt

    populated = build_triage_system_prompt([_prior("carpal_tunnel", recall="recall blob")])
    assert "Hi, I'm Sarjy." in populated
