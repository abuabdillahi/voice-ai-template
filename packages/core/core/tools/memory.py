"""Episodic memory tools exposed to the agent.

Two tools — :func:`remember` and :func:`recall` — give the realtime
agent a window into the mem0-backed episodic store. Together with the
system-prompt nudge ("save incidental facts the user mentions, recall
them before answering personal questions"), they realise the
episodic-memory promise from the PRD: facts mentioned in passing
during one session are findable in the next.

The implementations are intentionally small — they're thin adapters
over :mod:`core.memory`. The interesting design decision is the
schema: the registry's schema-derivation only supports primitive
parameters today (issue 06), so each tool takes a single ``str``.
"""

from __future__ import annotations

from core import memory
from core.tools.registry import ToolContext, tool

# Surfaced as a module-level constant so handlers and tests reference
# the same string. Phrased so the realtime model can verbalise it
# naturally if it has to apologise to the user.
_NO_AUTH_MSG = (
    "I can't save or recall memories in this session because I don't "
    "have your account credentials handy. Please try again after signing in."
)

# Returned by `recall` when mem0 has nothing to surface for the query.
# Intentionally short and conversational — the agent reads this back
# verbatim and we want it to flow naturally in speech.
_NO_RECALL_MSG = "I don't have anything relevant remembered yet."


@tool
async def remember(ctx: ToolContext, content: str) -> str:
    """Save an incidental fact the user mentioned about themselves.

    Use this whenever the user mentions facts that don't fit a named
    preference key — interests, relationships, ongoing projects, things
    they're learning, or anything else they say in passing that you'd
    want to surface in a later conversation. ``content`` is the raw
    fact; mem0 handles deduplication and update semantics on its end.
    """
    if ctx.supabase_access_token is None:
        ctx.log.warning("remember.no_access_token")
        return _NO_AUTH_MSG
    memory.remember(
        ctx.user,
        content,
        supabase_token=ctx.supabase_access_token,
    )
    return "Got it — I'll remember that."


@tool
async def recall(ctx: ToolContext, query: str) -> str:
    """Look up incidental facts the user mentioned in earlier sessions.

    Use this before answering personal questions about the user's life,
    interests, ongoing projects, or relationships. ``query`` should be
    a short phrase describing what you're looking for ("Spanish",
    "kids' names", "weekend plans") — mem0 runs a similarity search and
    returns the top matches. The result is one fact per line; if mem0
    finds nothing relevant the tool returns a polite "no recall"
    message rather than the empty string.
    """
    if ctx.supabase_access_token is None:
        ctx.log.warning("recall.no_access_token")
        return _NO_AUTH_MSG
    memories = memory.recall(
        ctx.user,
        query,
        supabase_token=ctx.supabase_access_token,
    )
    if not memories:
        return _NO_RECALL_MSG
    # Newline-joined so the realtime model can speak each fact as a
    # separate clause if it chooses; alternatively it can summarise the
    # bundle. The registry's contract requires a string return.
    return "\n".join(m.content for m in memories if m.content)


__all__ = ["recall", "remember"]
