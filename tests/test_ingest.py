import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest

from eventhub.ingest import BATCH_SIZE, Event, ingest


def make_event(**overrides):
    values = {
        "occurred_at": datetime(2026, 11, 26, 12, 0, tzinfo=UTC),
        "source": "web-01",
        "event_id": uuid.uuid4(),
        "severity": 4,
        "message": "Login failed",
    }
    values.update(overrides)
    return Event(**values)


def test_control_characters_are_removed():
    event = make_event(message="ok\nFAKE LOG LINE\r\x00")
    assert "\n" not in event.message
    assert "\r" not in event.message
    assert "\x00" not in event.message


def test_timestamp_is_normalised_to_naive_utc():
    plus_one = timezone(timedelta(hours=1))
    event = make_event(occurred_at=datetime(2026, 11, 26, 13, 0, tzinfo=plus_one))
    assert event.occurred_at == datetime(2026, 11, 26, 12, 0)
    assert event.occurred_at.tzinfo is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"occurred_at": datetime(2026, 11, 26, 12, 0)},  # naive
        {"source": "Bad Source!"},
        {"source": ""},
        {"source": "web-01\n"},
        {"severity": 8},
        {"severity": -1},
        {"message": "   "},
        {"message": "x" * 1001},
        {"event_id": "not-a-uuid"},
    ],
)
def test_invalid_events_are_rejected(overrides):
    with pytest.raises(ValueError):
        make_event(**overrides)


class FakeCursor:
    def __init__(self):
        self.batches = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def executemany(self, sql, rows):
        assert sql.count("%s") == 6  # parameterised only
        self.batches.append(rows)


class FakeConn:
    def __init__(self):
        self.cursor_obj = FakeCursor()

    def cursor(self):
        return self.cursor_obj


def test_ingest_splits_into_bounded_batches():
    conn = FakeConn()
    events = [make_event() for _ in range(BATCH_SIZE + 5)]
    assert ingest(conn, events, ingested_by=3) == BATCH_SIZE + 5
    assert [len(b) for b in conn.cursor_obj.batches] == [BATCH_SIZE, 5]


def test_ingest_records_who_submitted_the_events():
    conn = FakeConn()
    ingest(conn, [make_event()], ingested_by=42)
    assert conn.cursor_obj.batches[0][0][-1] == 42


def test_ingest_handles_empty_input():
    conn = FakeConn()
    assert ingest(conn, []) == 0
    assert conn.cursor_obj.batches == []
