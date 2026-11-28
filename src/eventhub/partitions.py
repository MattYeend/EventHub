"""Monthly partition maintenance and retention for the events table."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from . import audit
from .config import MIN_RETENTION_MONTHS
from .db import Connection, dict_cursor

LOCK_NAME = "eventhub_partitions"
LOCK_TIMEOUT_SECONDS = 30
MIN_CREATE_AHEAD = 3
MAX_CREATE_AHEAD = 24
CATCH_ALL = "pmax"

_NAME = re.compile(r"p(?P<year>\d{4})_(?P<month>\d{2})")

_PARTITIONS_SQL = (
    "SELECT PARTITION_NAME AS name FROM information_schema.PARTITIONS "
    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'events' AND PARTITION_NAME IS NOT NULL "
    "ORDER BY PARTITION_ORDINAL_POSITION"
)


class PartitionError(RuntimeError):
    """Raised when partition maintenance cannot proceed safely."""


@dataclass(frozen=True, slots=True)
class Plan:
    to_add: tuple[date, ...]
    to_drop: tuple[date, ...]


def first_of_month(value: date) -> date:
    return value.replace(day=1)


def add_months(value: date, months: int) -> date:
    """First day of the month that is `months` after (or before) the month of `value`."""
    index = value.year * 12 + (value.month - 1) + months
    return date(index // 12, index % 12 + 1, 1)


def partition_name(month: date) -> str:
    return f"p{month.year:04d}_{month.month:02d}"


def parse_partition_name(name: str) -> date | None:
    """Return the month for a 'pYYYY_MM' name, or None for anything else (such as pmax)."""
    match = _NAME.fullmatch(name)
    if match is None:
        return None
    year, month = int(match["year"]), int(match["month"])
    if not 1 <= month <= 12 or year < 1:
        return None
    return date(year, month, 1)


def _check(create_ahead: int, retain_months: int) -> None:
    if not MIN_CREATE_AHEAD <= create_ahead <= MAX_CREATE_AHEAD:
        raise PartitionError(
            f"create-ahead must be between {MIN_CREATE_AHEAD} and {MAX_CREATE_AHEAD}"
        )
    if retain_months < MIN_RETENTION_MONTHS:
        raise PartitionError(f"retain-months must be at least {MIN_RETENTION_MONTHS}")


def plan(existing: Iterable[date], today: date, *, create_ahead: int, retain_months: int) -> Plan:
    """Work out which months to add and which to drop. Pure, so it is easy to test."""
    _check(create_ahead, retain_months)
    months = sorted(set(existing))
    current = first_of_month(today)
    target = add_months(current, create_ahead)

    to_add: list[date] = []
    next_month = add_months(months[-1], 1) if months else current
    while next_month <= target:
        to_add.append(next_month)
        next_month = add_months(next_month, 1)

    cutoff = add_months(current, -retain_months)
    return Plan(tuple(to_add), tuple(m for m in months if m < cutoff))


def add_statement(months: Iterable[date]) -> str:
    """Split the catch-all partition into the given months. Built only from dates."""
    parts = [
        f"PARTITION {partition_name(m)} VALUES LESS THAN ('{add_months(m, 1).isoformat()}')"
        for m in months
    ]
    if not parts:
        raise ValueError("At least one month is required")
    parts.append(f"PARTITION {CATCH_ALL} VALUES LESS THAN (MAXVALUE)")
    return f"ALTER TABLE events REORGANIZE PARTITION {CATCH_ALL} INTO ({', '.join(parts)})"


def drop_statement(month: date) -> str:
    return f"ALTER TABLE events DROP PARTITION {partition_name(month)}"


def maintain(
    conn: Connection,
    *,
    today: date,
    create_ahead: int = MIN_CREATE_AHEAD,
    retain_months: int,
    dry_run: bool = False,
) -> list[str]:
    """Create upcoming partitions and drop expired ones. Returns the statements involved.

    Safe to run daily: a second run finds nothing to do. MySQL commits DDL implicitly, so
    audit rows are committed before and after each drop.
    """
    _check(create_ahead, retain_months)
    statements: list[str] = []
    with dict_cursor(conn) as cur:
        cur.execute("SELECT GET_LOCK(%s, %s) AS got", (LOCK_NAME, LOCK_TIMEOUT_SECONDS))
        row = cur.fetchone()
        if not row or row["got"] != 1:
            raise PartitionError("Could not obtain the partition lock")
        try:
            cur.execute(_PARTITIONS_SQL)
            names = [str(r["name"]) for r in cur.fetchall()]
            if CATCH_ALL not in names:
                raise PartitionError(f"The events table has no {CATCH_ALL} partition")
            months = [m for n in names if (m := parse_partition_name(n)) is not None]
            changes = plan(months, today, create_ahead=create_ahead, retain_months=retain_months)

            if changes.to_add:
                statement = add_statement(changes.to_add)
                statements.append(statement)
                if not dry_run:
                    cur.execute(statement)
                    created = ", ".join(partition_name(m) for m in changes.to_add)
                    audit.record(conn, "partition.create", target="events", detail=created)
                    conn.commit()

            for month in changes.to_drop:
                name = partition_name(month)  # built from a date, never from input
                statement = drop_statement(month)
                statements.append(statement)
                if dry_run:
                    continue
                cur.execute(
                    f"SELECT COUNT(*) AS n FROM events PARTITION ({name})"  # noqa: S608  # nosec B608
                )
                count_row = cur.fetchone()
                rows = int(count_row["n"]) if count_row else 0
                target = f"events:{name}"
                audit.record(conn, "partition.drop_attempt", target=target, detail=f"rows={rows}")
                conn.commit()
                cur.execute(statement)
                audit.record(conn, "partition.drop", target=target, detail=f"rows={rows}")
                conn.commit()
        finally:
            cur.execute("SELECT RELEASE_LOCK(%s) AS released", (LOCK_NAME,))
            cur.fetchall()
    return statements
