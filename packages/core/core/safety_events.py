"""Safety-event audit log.

Persists every tier-1 / tier-2 red-flag escalation as a ``safety_events``
row so a clinician reviewer can audit escalations after the fact. The
module surface mirrors :mod:`core.conversations` and
:mod:`core.preferences`: typed insert under the user's JWT, typed read
of the user's own events. RLS (``0004_safety_events.sql``) enforces
isolation at the database level.

The module is best-effort from the agent worker's perspective — a
failure to insert is logged but never blocks the escalation script or
the session-end. The safety floor (the regex+classifier screen) does
*not* depend on persistence; persistence is the audit trail.
"""

from __future__ import annotations

import builtins
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from core.auth import User
from core.supabase import get_user_client

_TABLE = "safety_events"

_list = builtins.list


@dataclass(frozen=True, slots=True)
class SafetyEvent:
    """One persisted red-flag escalation row.

    The ``tier`` and ``source`` fields are constrained at the database
    by ``CHECK`` clauses; the dataclass mirrors the on-disk values
    rather than re-enumerating them in Python. Bumping the allowed
    values is a coordinated migration plus an enum extension in
    :mod:`core.safety`.
    """

    id: UUID
    conversation_id: UUID
    user_id: UUID
    tier: str
    source: str
    matched_flags: builtins.list[str]
    utterance: str
    created_at: datetime


def _parse_uuid(value: Any) -> UUID:
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _parse_flags(value: Any) -> builtins.list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        # PostgREST sometimes returns jsonb arrays already-decoded; this
        # branch is defensive for legacy clients.
        import json

        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return []
        if isinstance(decoded, list):
            return [str(item) for item in decoded]
    return []


def _row_to_event(row: dict[str, Any]) -> SafetyEvent:
    return SafetyEvent(
        id=_parse_uuid(row["id"]),
        conversation_id=_parse_uuid(row["conversation_id"]),
        user_id=_parse_uuid(row["user_id"]),
        tier=str(row["tier"]),
        source=str(row["source"]),
        matched_flags=_parse_flags(row.get("matched_flags")),
        utterance=str(row["utterance"]),
        created_at=_parse_datetime(row["created_at"]),
    )


def record(
    conversation_id: UUID,
    user_id: UUID,
    tier: str,
    source: str,
    matched_flags: builtins.list[str] | tuple[str, ...],
    utterance: str,
    *,
    supabase_token: str,
) -> SafetyEvent:
    """Insert a ``safety_events`` row and return the persisted record.

    The user's Supabase JWT is required because the insert RLS
    predicate is ``auth.uid() = user_id``. Without it, PostgREST hits
    the table as the anon role and the insert silently fails — we
    surface that loudly as ``RuntimeError`` rather than dropping the
    audit row.
    """
    client = get_user_client(supabase_token)
    payload: dict[str, Any] = {
        "conversation_id": str(conversation_id),
        "user_id": str(user_id),
        "tier": tier,
        "source": source,
        "matched_flags": list(matched_flags),
        "utterance": utterance,
    }
    response = client.table(_TABLE).insert(payload).execute()
    rows = cast(_list[dict[str, Any]], response.data or [])
    if not rows:
        raise RuntimeError("safety_events insert returned no rows; check RLS / user_id mapping")
    return _row_to_event(rows[0])


def list_for_user(
    user: User,
    *,
    supabase_token: str,
) -> builtins.list[SafetyEvent]:
    """Return the user's safety events, newest first.

    The clinician-reviewer queue (post-MVP) will read this same table
    via a different scope. For now the only consumer is a per-user read
    from the API layer, so the listing is naturally bounded by the
    user's own escalation history.
    """
    client = get_user_client(supabase_token)
    response = (
        client.table(_TABLE)
        .select("*")
        .eq("user_id", str(user.id))
        .order("created_at", desc=True)
        .execute()
    )
    rows = cast(_list[dict[str, Any]], response.data or [])
    return [_row_to_event(row) for row in rows]


__all__ = ["SafetyEvent", "list_for_user", "record"]
