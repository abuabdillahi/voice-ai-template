"""Conversation transcripts.

Persists every voice conversation as a parent ``conversations`` row
plus one ``messages`` row per turn (user, assistant, tool). The agent
worker writes these mid-session via :func:`start`, :func:`append_message`,
and :func:`end`; the API exposes :func:`list_for_user` and :func:`get`
for the web app's history pages.

Like :mod:`core.preferences`, every call accepts the user's Supabase
access token so PostgREST runs the query as the authenticated user and
RLS policies (``0002_conversations.sql``) apply. Without the token the
query hits the table as the ``anon`` role and silently returns no rows.

``end`` calls :func:`generate_summary_and_recall` automatically when
the caller does not supply one and the conversation has at least three
messages (the threshold is the AC's; below it, a summary would be near-
content-free). Summarisation uses the OpenAI client; tests inject a
callable to stay deterministic and offline.
"""

from __future__ import annotations

import builtins
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from core.auth import User
from core.conditions import CONDITIONS
from core.config import Settings, get_settings
from core.supabase import get_user_client

# `list` shadows the builtin (public API name). Bind the original up
# front so cast targets in the listing function still resolve correctly.
_list = builtins.list

_CONVERSATIONS_TABLE = "conversations"
_MESSAGES_TABLE = "messages"

# Threshold (AC §"end triggers summary generation when threshold met"):
# below three messages a summary would be near-content-free, so we skip
# the LLM round-trip and leave summary NULL.
_SUMMARY_MESSAGE_COUNT_THRESHOLD = 3

# Type for the optional summariser callable injected by tests. Returns
# a tuple ``(summary, recall_context)`` — the one-sentence preview that
# drives the history-list UI plus the richer free-text blob the next
# session reads at prompt-injection time. ``recall_context`` is allowed
# to be ``None`` so a malformed-JSON / network-failure path can still
# populate ``summary`` via the truncation fallback without inventing a
# recall blob.
SummaryFn = Callable[[builtins.list["Message"]], tuple[str, str | None]]


@dataclass(frozen=True, slots=True)
class Message:
    """A single turn within a conversation.

    ``content`` carries the user's or assistant's spoken text. For
    ``tool`` messages, ``content`` is conventionally the empty string
    and the structured payload lives in ``tool_name`` / ``tool_args``
    / ``tool_result``.
    """

    id: UUID
    conversation_id: UUID
    role: str
    content: str
    tool_name: str | None
    tool_args: dict[str, Any] | None
    tool_result: Any | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Conversation:
    """A conversation with its messages, ordered by ``created_at``."""

    id: UUID
    user_id: UUID
    started_at: datetime
    ended_at: datetime | None
    summary: str | None
    metadata: dict[str, Any]
    messages: builtins.list[Message] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ConversationSummary:
    """Lightweight projection used by :func:`list_for_user`.

    The list page never needs the full message log, just enough to
    render a row. Carrying ``message_count`` here keeps the ``GET
    /conversations`` response stable as the schema grows.
    """

    id: UUID
    started_at: datetime
    ended_at: datetime | None
    summary: str | None
    message_count: int


@dataclass(frozen=True, slots=True)
class PriorSession:
    """One condition-bearing prior session, projected for prompt injection.

    Returned by :func:`list_recent_with_recall`. Deliberately a separate
    shape from :class:`ConversationSummary` so the ``/conversations``
    API endpoint contract — which the web history page consumes — is
    not affected by the addition of ``recall_context``. The agent
    worker is the only consumer.
    """

    started_at: datetime
    identified_condition_id: str
    recall_context: str | None


def _parse_uuid(value: Any) -> UUID:
    """Coerce a Supabase response field to :class:`UUID`."""
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def _parse_datetime(value: Any) -> datetime:
    """Coerce a Supabase ``timestamptz`` string to :class:`datetime`."""
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _parse_optional_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    return _parse_datetime(value)


def _row_to_message(row: dict[str, Any]) -> Message:
    return Message(
        id=_parse_uuid(row["id"]),
        conversation_id=_parse_uuid(row["conversation_id"]),
        role=str(row["role"]),
        content=str(row["content"]),
        tool_name=row.get("tool_name"),
        tool_args=cast(dict[str, Any] | None, row.get("tool_args")),
        tool_result=row.get("tool_result"),
        created_at=_parse_datetime(row["created_at"]),
    )


def start(
    user: User,
    *,
    supabase_token: str | None = None,
) -> UUID:
    """Insert a new ``conversations`` row and return its id.

    ``supabase_token`` is the user's Supabase JWT. Without it the
    insert fails the RLS ``with check`` predicate and the function
    raises — a session-bootstrap bug we want to surface loudly rather
    than silently dropping transcripts.
    """
    if supabase_token is None:
        raise PermissionError(
            "core.conversations.start requires the user's Supabase access token "
            "for the RLS-scoped insert. None was supplied."
        )
    client = get_user_client(supabase_token)
    payload = {"user_id": str(user.id)}
    response = client.table(_CONVERSATIONS_TABLE).insert(payload).execute()
    rows = cast(_list[dict[str, Any]], response.data or [])
    if not rows:
        # PostgREST under RLS returns no row when the policy denies the
        # insert; a missing user_id is the only realistic cause here.
        raise RuntimeError("conversation insert returned no rows; check RLS / user mapping")
    return _parse_uuid(rows[0]["id"])


def append_message(
    conv_id: UUID,
    role: str,
    content: str,
    *,
    tool_name: str | None = None,
    tool_args: dict[str, Any] | None = None,
    tool_result: Any | None = None,
    supabase_token: str | None = None,
) -> Message:
    """Insert a message into a conversation and return the persisted row.

    Ordering across messages is enforced by the server-set
    ``created_at`` column — callers do not supply timestamps. The role
    ``CHECK`` constraint at the database is the source of truth for
    valid values; we re-check here so the API call fails fast with a
    clear message rather than a Postgres error string.
    """
    if role not in {"user", "assistant", "tool"}:
        raise ValueError(f"invalid message role {role!r}")
    if supabase_token is None:
        raise PermissionError(
            "core.conversations.append_message requires the user's Supabase access token."
        )
    client = get_user_client(supabase_token)
    payload: dict[str, Any] = {
        "conversation_id": str(conv_id),
        "role": role,
        "content": content,
    }
    if tool_name is not None:
        payload["tool_name"] = tool_name
    if tool_args is not None:
        payload["tool_args"] = tool_args
    if tool_result is not None:
        payload["tool_result"] = tool_result
    response = client.table(_MESSAGES_TABLE).insert(payload).execute()
    rows = cast(_list[dict[str, Any]], response.data or [])
    if not rows:
        raise RuntimeError("message insert returned no rows; check RLS / conversation ownership")
    return _row_to_message(rows[0])


def _list_messages(
    conv_id: UUID,
    *,
    supabase_token: str,
) -> builtins.list[Message]:
    """Fetch every message for ``conv_id``, ordered by ``created_at``."""
    client = get_user_client(supabase_token)
    response = (
        client.table(_MESSAGES_TABLE)
        .select("*")
        .eq("conversation_id", str(conv_id))
        .order("created_at", desc=False)
        .execute()
    )
    rows = cast(_list[dict[str, Any]], response.data or [])
    return [_row_to_message(row) for row in rows]


def end(
    conv_id: UUID,
    summary: str | None = None,
    *,
    supabase_token: str | None = None,
    summary_fn: SummaryFn | None = None,
    settings: Settings | None = None,
) -> None:
    """Set ``ended_at`` (and optionally ``summary``) on a conversation.

    When ``summary`` is None and the conversation has at least
    :data:`_SUMMARY_MESSAGE_COUNT_THRESHOLD` messages, this calls
    :func:`generate_summary_and_recall` to mint a ``(summary,
    recall_context)`` pair and also runs
    :func:`extract_identified_condition` over the same message list to
    populate the structured ``identified_condition_id`` column. Tests
    inject ``summary_fn`` to keep the path deterministic; production
    passes nothing and the OpenAI-backed default is used.

    When ``summary`` is supplied explicitly the function does not fetch
    the message list — there is no second tuple element to derive — so
    the new recall columns stay NULL on that path. This matches the
    pre-recall behaviour for the explicit-summary call site.
    """
    if supabase_token is None:
        raise PermissionError("core.conversations.end requires the user's Supabase access token.")
    client = get_user_client(supabase_token)

    resolved_summary = summary
    resolved_recall_context: str | None = None
    resolved_condition_id: str | None = None
    if resolved_summary is None:
        messages = _list_messages(conv_id, supabase_token=supabase_token)
        if len(messages) >= _SUMMARY_MESSAGE_COUNT_THRESHOLD:
            resolved_summary, resolved_recall_context = generate_summary_and_recall(
                conv_id,
                messages=messages,
                summary_fn=summary_fn,
                settings=settings,
            )
            resolved_condition_id = extract_identified_condition(messages)

    update: dict[str, Any] = {"ended_at": "now()"}
    # PostgREST does not interpret SQL function literals in payloads;
    # we let the database default for `now()` apply by using an ISO
    # string instead. Building one here keeps the wire-format simple.
    update["ended_at"] = datetime.now().astimezone().isoformat()
    if resolved_summary is not None:
        update["summary"] = resolved_summary
    if resolved_recall_context is not None:
        update["recall_context"] = resolved_recall_context
    if resolved_condition_id is not None:
        update["identified_condition_id"] = resolved_condition_id

    client.table(_CONVERSATIONS_TABLE).update(update).eq("id", str(conv_id)).execute()


def list_for_user(
    user: User,
    *,
    limit: int = 50,
    offset: int = 0,
    supabase_token: str | None = None,
) -> builtins.list[ConversationSummary]:
    """Return ``user``'s conversations as compact summaries.

    Results are ordered by ``started_at`` descending so the most
    recent conversation appears first — the index defined in the
    migration covers exactly this query plan.
    """
    if supabase_token is None:
        raise PermissionError(
            "core.conversations.list_for_user requires the user's Supabase access token."
        )
    client = get_user_client(supabase_token)
    # `messages(count)` asks PostgREST to embed an aggregated row count
    # for the related table. RLS still scopes the underlying rows so a
    # different user's messages cannot inflate the number.
    response = (
        client.table(_CONVERSATIONS_TABLE)
        .select("id,started_at,ended_at,summary,messages(count)")
        .eq("user_id", str(user.id))
        .order("started_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    rows = cast(_list[dict[str, Any]], response.data or [])
    summaries: builtins.list[ConversationSummary] = []
    for row in rows:
        # PostgREST returns the embedded count as a list of one dict
        # like ``[{"count": 3}]``. Some Supabase versions surface a
        # bare int. Handle both.
        raw_count = row.get("messages")
        message_count = 0
        if isinstance(raw_count, list) and raw_count:
            first = raw_count[0]
            if isinstance(first, dict) and "count" in first:
                message_count = int(first["count"])
        elif isinstance(raw_count, int):
            message_count = raw_count
        summaries.append(
            ConversationSummary(
                id=_parse_uuid(row["id"]),
                started_at=_parse_datetime(row["started_at"]),
                ended_at=_parse_optional_datetime(row.get("ended_at")),
                summary=row.get("summary"),
                message_count=message_count,
            )
        )
    return summaries


def get(
    user: User,
    conv_id: UUID,
    *,
    supabase_token: str | None = None,
) -> Conversation | None:
    """Return one conversation with its messages, or ``None`` if not found.

    RLS turns "owned by another user" into "doesn't exist" — both
    surface here as ``None``. The route layer maps that to a 404. We
    deliberately do not leak "exists but is not yours" because that
    itself would be a privacy bug.
    """
    if supabase_token is None:
        raise PermissionError("core.conversations.get requires the user's Supabase access token.")
    client = get_user_client(supabase_token)
    response = (
        client.table(_CONVERSATIONS_TABLE)
        .select("*")
        .eq("id", str(conv_id))
        .eq("user_id", str(user.id))
        .limit(1)
        .execute()
    )
    rows = cast(_list[dict[str, Any]], response.data or [])
    if not rows:
        return None
    row = rows[0]
    messages = _list_messages(conv_id, supabase_token=supabase_token)
    return Conversation(
        id=_parse_uuid(row["id"]),
        user_id=_parse_uuid(row["user_id"]),
        started_at=_parse_datetime(row["started_at"]),
        ended_at=_parse_optional_datetime(row.get("ended_at")),
        summary=row.get("summary"),
        metadata=cast(dict[str, Any], row.get("metadata") or {}),
        messages=messages,
    )


def generate_summary_and_recall(
    conv_id: UUID,  # noqa: ARG001 — accepted for symmetry with the AC signature
    *,
    messages: builtins.list[Message] | None = None,
    summary_fn: SummaryFn | None = None,
    settings: Settings | None = None,
) -> tuple[str, str | None]:
    """Produce a one-sentence summary plus a richer recall blob.

    The default implementation calls OpenAI (using the API key in
    :class:`Settings`) with the message history. Tests pass an
    explicit ``summary_fn`` to bypass the network round-trip — that
    callable receives the same :class:`Message` list and returns the
    same ``(summary, recall_context)`` tuple shape.

    ``messages`` is accepted as a parameter so :func:`end` can pass
    the list it already fetched, avoiding a duplicate read.

    Failure modes (malformed JSON, network exception, missing OpenAI
    install) yield ``(_truncated_fallback(transcript), None)`` — the
    history-list UI still gets a populated ``summary`` and the next
    session simply sees no recall context for this conversation.
    """
    if messages is None:
        # The function is otherwise stateless wrt Supabase; if a caller
        # asks for a summary by id alone, we cannot fulfil it without a
        # token. Surface the contract issue instead of pretending.
        raise ValueError(
            "generate_summary_and_recall requires a `messages` list; pass the result of "
            "`_list_messages` from a token-scoped call site."
        )

    if summary_fn is not None:
        return summary_fn(messages)

    return _default_summary_and_recall_fn(messages, settings=settings)


def _default_summary_and_recall_fn(
    messages: builtins.list[Message],
    *,
    settings: Settings | None = None,
) -> tuple[str, str | None]:
    """Default summary+recall implementation backed by the OpenAI Python client.

    One gpt-4o-mini call requests a small JSON object with two
    top-level keys: ``summary`` (one short sentence — the history-list
    UI's existing shape) and ``recall_context`` (a richer blob covering
    what was discussed, what was recommended, and any user-reported
    outcomes). Tool messages for ``recommend_treatment`` are included
    verbatim in the prompt input so the LLM can ground the recall blob
    in what the agent actually recommended.

    Imported lazily so the unit-test path that injects a callable
    never pays the OpenAI import cost.
    """
    settings = settings or get_settings()

    # Build a single concatenated prompt of role-tagged turns. Tool
    # messages render with their args+result for `recommend_treatment`
    # so the LLM can describe what was recommended; other tool calls
    # render as a compact tag.
    turns: builtins.list[str] = []
    for m in messages:
        if m.role == "tool":
            if m.tool_name == "recommend_treatment":
                args_blob = json.dumps(m.tool_args or {}, sort_keys=True)
                result_blob = json.dumps(m.tool_result, sort_keys=True, default=str)
                turns.append(f"[tool recommend_treatment args={args_blob} result={result_blob}]")
            else:
                turns.append(f"[tool {m.tool_name or 'unknown'}]")
        else:
            turns.append(f"{m.role}: {m.content}")
    transcript = "\n".join(turns)

    try:
        from openai import OpenAI
    except ImportError:  # pragma: no cover — openai always installed via livekit-agents extra
        return (_truncated_fallback(transcript), None)

    client = OpenAI(api_key=settings.openai_api_key)
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You summarise voice triage conversations between a "
                        "user and an educational triage assistant. Reply with "
                        'a JSON object with exactly two keys: "summary" — one '
                        "short sentence suitable for a history list — and "
                        '"recall_context" — a richer paragraph covering what '
                        "was discussed, what (if anything) was recommended, "
                        "and any user-reported outcomes. Reply with the JSON "
                        "object only — no preamble, no Markdown fence."
                    ),
                },
                {"role": "user", "content": transcript},
            ],
            response_format={"type": "json_object"},
            max_tokens=400,
            temperature=0.2,
        )
    except Exception:  # noqa: BLE001 — best-effort summary, never crash session-end.
        return (_truncated_fallback(transcript), None)

    choice = response.choices[0] if response.choices else None
    content = choice.message.content if choice and choice.message else None
    if not content:
        return (_truncated_fallback(transcript), None)

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return (_truncated_fallback(transcript), None)

    if not isinstance(parsed, dict):
        return (_truncated_fallback(transcript), None)

    summary_value = parsed.get("summary")
    recall_value = parsed.get("recall_context")
    summary_text = (
        summary_value.strip() if isinstance(summary_value, str) and summary_value.strip() else None
    )
    recall_text = (
        recall_value.strip() if isinstance(recall_value, str) and recall_value.strip() else None
    )
    if summary_text is None:
        return (_truncated_fallback(transcript), None)
    return (summary_text, recall_text)


def extract_identified_condition(
    messages: builtins.list[Message],
) -> str | None:
    """Return the most recent successful ``recommend_treatment`` condition id.

    Scans ``messages`` in reverse for ``tool`` rows where
    ``tool_name == "recommend_treatment"`` and the ``tool_result`` is a
    successful payload (no ``error`` key). The ``condition_id`` is read
    from ``tool_args``, validated against
    :data:`core.conditions.CONDITIONS`, and returned. Unknown ids,
    error payloads, and message lists with no successful call all
    return ``None``.

    Pure function — no Supabase, no LLM. The structured
    ``identified_condition_id`` column is the load-bearing fact that
    drives the next session's opener; deriving it deterministically
    from the persisted tool transcript keeps it auditable and outside
    the surface-area of LLM hallucination.
    """
    for message in reversed(messages):
        if message.role != "tool":
            continue
        if message.tool_name != "recommend_treatment":
            continue
        result = message.tool_result
        if isinstance(result, dict) and "error" in result:
            continue
        if result is None:
            continue
        args = message.tool_args or {}
        condition_id = args.get("condition_id") if isinstance(args, dict) else None
        if not isinstance(condition_id, str):
            continue
        if condition_id not in CONDITIONS:
            return None
        return condition_id
    return None


def list_recent_with_recall(
    user: User,
    *,
    limit: int = 3,
    supabase_token: str | None = None,
) -> builtins.list[PriorSession]:
    """Return the user's most recent condition-bearing prior sessions.

    Filters to rows where ``identified_condition_id IS NOT NULL`` so a
    first-time user, or a returning user whose prior sessions all ended
    without an identified condition, sees an empty list — and the
    triage prompt builder degrades to today's static prompt.

    Ordered ``started_at`` descending; capped at ``limit`` (defaults to
    3 per the PRD's bounded-prompt rule). Returns the projection
    :class:`PriorSession` so the existing ``/conversations`` API
    endpoint contract — which serves :class:`ConversationSummary` — is
    unaffected.
    """
    if supabase_token is None:
        raise PermissionError(
            "core.conversations.list_recent_with_recall requires the user's "
            "Supabase access token."
        )
    client = get_user_client(supabase_token)
    response = (
        client.table(_CONVERSATIONS_TABLE)
        .select("started_at,identified_condition_id,recall_context")
        .eq("user_id", str(user.id))
        .filter("identified_condition_id", "not.is", "null")
        .order("started_at", desc=True)
        .limit(limit)
        .execute()
    )
    rows = cast(_list[dict[str, Any]], response.data or [])
    sessions: builtins.list[PriorSession] = []
    for row in rows:
        condition_id = row.get("identified_condition_id")
        if not isinstance(condition_id, str) or not condition_id:
            continue
        recall = row.get("recall_context")
        sessions.append(
            PriorSession(
                started_at=_parse_datetime(row["started_at"]),
                identified_condition_id=condition_id,
                recall_context=recall if isinstance(recall, str) else None,
            )
        )
    return sessions


def _truncated_fallback(transcript: str) -> str:
    """Best-effort summary when OpenAI is unavailable.

    Returns the first ~120 characters of the transcript. Good enough
    to populate the history list rather than leave it ``NULL`` after a
    transient outage.
    """
    cleaned = transcript.replace("\n", " ").strip()
    if len(cleaned) <= 120:
        return cleaned
    return cleaned[:117].rstrip() + "…"


__all__ = [
    "Conversation",
    "ConversationSummary",
    "Message",
    "PriorSession",
    "SummaryFn",
    "append_message",
    "end",
    "extract_identified_condition",
    "generate_summary_and_recall",
    "get",
    "list_for_user",
    "list_recent_with_recall",
    "start",
]
