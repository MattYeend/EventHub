"""Event ingestion and query endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from .accounts import Role, User
from .deps import ConnDep, require_roles
from .ingest import MAX_MESSAGE_LENGTH, MAX_SEVERITY, SOURCE_REGEX, Event, ingest
from .reporting import MAX_LIST_LIMIT, list_events
from .security import utcnow

router = APIRouter(prefix="/events", tags=["events"])

MAX_BATCH = 1000

Ingester = Annotated[User, Depends(require_roles(Role.INGEST, Role.ADMIN))]
Reporter = Annotated[User, Depends(require_roles(Role.REPORTER, Role.ADMIN))]


class EventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    occurred_at: AwareDatetime
    source: str = Field(pattern=SOURCE_REGEX)
    event_id: UUID
    severity: int = Field(ge=0, le=MAX_SEVERITY)
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)


class EventBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[EventIn] = Field(min_length=1, max_length=MAX_BATCH)


class IngestResult(BaseModel):
    submitted: int


class EventOut(BaseModel):
    id: int
    occurred_at: datetime
    source: str
    event_id: UUID
    severity: int
    message: str


def _naive_utc(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


@router.post("", response_model=IngestResult)
def ingest_events(body: EventBatch, conn: ConnDep, user: Ingester) -> IngestResult:
    """Idempotent: re-sending the same events never creates duplicates."""
    try:
        events = [Event(**item.model_dump()) for item in body.events]
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return IngestResult(submitted=ingest(conn, events, ingested_by=user.id))


@router.get("", response_model=list[EventOut])
def query_events(
    conn: ConnDep,
    user: Reporter,
    since: AwareDatetime | None = None,
    until: AwareDatetime | None = None,
    source: Annotated[str | None, Query(pattern=SOURCE_REGEX)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[EventOut]:
    """Defaults to the last 24 hours. The window may not exceed 31 days."""
    until_utc = _naive_utc(until) if until else utcnow()
    since_utc = _naive_utc(since) if since else until_utc - timedelta(hours=24)
    try:
        stored = list_events(
            conn, since=since_utc, until=until_utc, source=source, limit=limit, offset=offset
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return [EventOut.model_validate(e, from_attributes=True) for e in stored]
