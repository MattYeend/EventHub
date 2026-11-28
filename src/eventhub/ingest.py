"""Validated, idempotent batch ingestion of events."""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import batched

from .db import Connection
from .sanitise import strip_control

BATCH_SIZE = 1000
MAX_MESSAGE_LENGTH = 1000
MAX_SEVERITY = 7  # syslog scale, 0 (emergency) to 7 (debug)
SOURCE_REGEX = r"^[a-z0-9._-]{1,64}$"

_SOURCE_PATTERN = re.compile(SOURCE_REGEX)

_INSERT_SQL = (
    "INSERT INTO events (occurred_at, source, event_id, severity, message, ingested_by) "
    "VALUES (%s, %s, %s, %s, %s, %s) "
    "ON DUPLICATE KEY UPDATE id = id"
)


@dataclass(frozen=True, slots=True)
class Event:
    occurred_at: datetime
    source: str
    event_id: uuid.UUID
    severity: int
    message: str

    def __post_init__(self) -> None:
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        if not _SOURCE_PATTERN.fullmatch(self.source):
            raise ValueError("source must match [a-z0-9._-] and be 1 to 64 characters")
        if not isinstance(self.event_id, uuid.UUID):
            raise ValueError("event_id must be a UUID")
        if not 0 <= self.severity <= MAX_SEVERITY:
            raise ValueError(f"severity must be 0 to {MAX_SEVERITY}")

        cleaned = strip_control(self.message)
        if not cleaned or len(cleaned) > MAX_MESSAGE_LENGTH:
            raise ValueError(f"message must be 1 to {MAX_MESSAGE_LENGTH} characters")

        # Frozen dataclass: normalise via object.__setattr__ in one place only.
        object.__setattr__(self, "message", cleaned)
        object.__setattr__(
            self, "occurred_at", self.occurred_at.astimezone(UTC).replace(tzinfo=None)
        )


def _rows(
    events: Iterable[Event], ingested_by: int | None
) -> Iterator[tuple[datetime, str, bytes, int, str, int | None]]:
    for e in events:
        yield (e.occurred_at, e.source, e.event_id.bytes, e.severity, e.message, ingested_by)


def ingest(conn: Connection, events: Iterable[Event], *, ingested_by: int | None = None) -> int:
    """Insert events in bounded batches; return the number submitted.

    Duplicates (same source, event_id and occurred_at) are ignored, so the
    call is safe to retry. The caller owns the transaction (see db.py).
    """
    submitted = 0
    with conn.cursor() as cur:
        for chunk in batched(_rows(events, ingested_by), BATCH_SIZE):
            cur.executemany(_INSERT_SQL, list(chunk))
            submitted += len(chunk)
    return submitted