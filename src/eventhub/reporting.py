"""Read-side queries for stored events."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .db import Connection, dict_cursor

MAX_LIST_LIMIT = 200
MAX_WINDOW = timedelta(days=31)

_SQL_ALL = (
    "SELECT id, occurred_at, source, event_id, severity, message FROM events "
    "WHERE occurred_at >= %s AND occurred_at < %s "
    "ORDER BY occurred_at DESC, id DESC LIMIT %s OFFSET %s"
)
_SQL_BY_SOURCE = (
    "SELECT id, occurred_at, source, event_id, severity, message FROM events "
    "WHERE occurred_at >= %s AND occurred_at < %s AND source = %s "
    "ORDER BY occurred_at DESC, id DESC LIMIT %s OFFSET %s"
)


@dataclass(frozen=True, slots=True)
class StoredEvent:
    id: int
    occurred_at: datetime  # timezone-aware, UTC
    source: str
    event_id: uuid.UUID
    severity: int
    message: str


def list_events(
    conn: Connection,
    *,
    since: datetime,
    until: datetime,
    source: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[StoredEvent]:
    """List events in a bounded UTC window (naive datetimes), newest first.

    A mandatory, bounded time window lets MySQL prune partitions, which is what keeps
    reads fast as the table grows.
    """
    if since >= until:
        raise ValueError("since must be earlier than until")
    if until - since > MAX_WINDOW:
        raise ValueError(f"The time window must not exceed {MAX_WINDOW.days} days")
    limit = max(1, min(int(limit), MAX_LIST_LIMIT))
    offset = max(0, int(offset))

    with dict_cursor(conn) as cur:
        if source is None:
            cur.execute(_SQL_ALL, (since, until, limit, offset))
        else:
            cur.execute(_SQL_BY_SOURCE, (since, until, source, limit, offset))
        rows = cur.fetchall()
    return [
        StoredEvent(
            id=int(r["id"]),
            occurred_at=r["occurred_at"].replace(tzinfo=UTC),
            source=str(r["source"]),
            event_id=uuid.UUID(bytes=bytes(r["event_id"])),
            severity=int(r["severity"]),
            message=str(r["message"]),
        )
        for r in rows
    ]