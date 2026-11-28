from datetime import date

import pytest

from eventhub.partitions import (
    PartitionError,
    add_months,
    add_statement,
    drop_statement,
    maintain,
    parse_partition_name,
    partition_name,
    plan,
)

TODAY = date(2026, 11, 27)
EXISTING = [date(2026, 11, 1), date(2026, 12, 1), date(2027, 1, 1)]


def test_add_months_crosses_year_boundaries():
    assert add_months(date(2026, 12, 1), 1) == date(2027, 1, 1)
    assert add_months(date(2026, 11, 1), 3) == date(2027, 2, 1)
    assert add_months(date(2027, 1, 1), -2) == date(2026, 11, 1)


def test_partition_names_round_trip():
    assert partition_name(date(2027, 2, 1)) == "p2027_02"
    assert parse_partition_name("p2027_02") == date(2027, 2, 1)


@pytest.mark.parametrize(
    "name", ["pmax", "p2027_13", "p2027_00", "p27_01", "P2027_01", "p2027_01; DROP TABLE users"]
)
def test_unexpected_names_are_ignored(name):
    assert parse_partition_name(name) is None


def test_first_run_adds_the_missing_month():
    changes = plan(EXISTING, TODAY, create_ahead=3, retain_months=12)
    assert changes.to_add == (date(2027, 2, 1),)
    assert changes.to_drop == ()


def test_second_run_has_nothing_to_do():
    existing = [*EXISTING, date(2027, 2, 1)]
    changes = plan(existing, TODAY, create_ahead=3, retain_months=12)
    assert changes.to_add == ()
    assert changes.to_drop == ()


def test_long_gap_is_caught_up_contiguously():
    changes = plan(EXISTING, date(2027, 5, 10), create_ahead=3, retain_months=12)
    assert changes.to_add[0] == date(2027, 2, 1)
    assert changes.to_add[-1] == date(2027, 8, 1)
    assert len(changes.to_add) == 7


def test_only_months_before_the_cutoff_are_dropped():
    existing = [add_months(date(2025, 1, 1), i) for i in range(25)]  # 2025-01 to 2027-01
    changes = plan(existing, TODAY, create_ahead=3, retain_months=12)
    assert date(2025, 10, 1) in changes.to_drop
    assert date(2025, 11, 1) not in changes.to_drop
    assert len(changes.to_drop) == 10


def test_current_and_future_months_are_never_dropped():
    existing = [add_months(date(2026, 1, 1), i) for i in range(16)]
    changes = plan(existing, TODAY, create_ahead=3, retain_months=3)
    assert all(month < date(2026, 11, 1) for month in changes.to_drop)


def test_unsafe_settings_are_rejected():
    with pytest.raises(PartitionError):
        plan(EXISTING, TODAY, create_ahead=2, retain_months=12)
    with pytest.raises(PartitionError):
        plan(EXISTING, TODAY, create_ahead=3, retain_months=2)


def test_add_statement_is_built_from_dates():
    expected = (
        "ALTER TABLE events REORGANIZE PARTITION pmax INTO ("
        "PARTITION p2027_02 VALUES LESS THAN ('2027-03-01'), "
        "PARTITION p2027_03 VALUES LESS THAN ('2027-04-01'), "
        "PARTITION pmax VALUES LESS THAN (MAXVALUE))"
    )
    assert add_statement([date(2027, 2, 1), date(2027, 3, 1)]) == expected


def test_add_statement_needs_a_month():
    with pytest.raises(ValueError):
        add_statement([])


def test_drop_statement_is_built_from_a_date():
    assert drop_statement(date(2025, 1, 1)) == "ALTER TABLE events DROP PARTITION p2025_01"


class FakeCursor:
    def __init__(self, names, rows=7):
        self.names = names
        self.rows = rows
        self.executed = []
        self._result = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if "GET_LOCK" in sql:
            self._result = [{"got": 1}]
        elif "information_schema.PARTITIONS" in sql:
            self._result = [{"name": n} for n in self.names]
        elif "COUNT(*)" in sql:
            self._result = [{"n": self.rows}]
        else:
            self._result = []

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return self._result


class FakeConn:
    def __init__(self, names):
        self.cur = FakeCursor(names)
        self.commits = 0

    def cursor(self, **kwargs):
        return self.cur

    def commit(self):
        self.commits += 1


CURRENT = ["p2026_11", "p2026_12", "p2027_01", "pmax"]


def audit_actions(conn):
    return [p[1] for sql, p in conn.cur.executed if sql.startswith("INSERT INTO audit_log")]


def test_dry_run_prints_statements_and_changes_nothing():
    conn = FakeConn(CURRENT)
    statements = maintain(conn, today=TODAY, retain_months=12, dry_run=True)
    assert len(statements) == 1 and "REORGANIZE" in statements[0]
    assert not any(sql.startswith("ALTER") for sql, _ in conn.cur.executed)
    assert audit_actions(conn) == []
    assert conn.commits == 0


def test_real_run_creates_the_partition_and_audits_it():
    conn = FakeConn(CURRENT)
    maintain(conn, today=TODAY, retain_months=12)
    assert any(sql.startswith("ALTER TABLE events REORGANIZE") for sql, _ in conn.cur.executed)
    assert audit_actions(conn) == ["partition.create"]


def test_up_to_date_table_needs_no_changes():
    conn = FakeConn([*CURRENT[:-1], "p2027_02", "pmax"])
    assert maintain(conn, today=TODAY, retain_months=12) == []


def test_drop_is_audited_with_the_row_count_before_and_after():
    conn = FakeConn(["p2025_01", *CURRENT[:-1], "p2027_02", "pmax"])
    statements = maintain(conn, today=TODAY, retain_months=12)
    assert statements == ["ALTER TABLE events DROP PARTITION p2025_01"]
    assert audit_actions(conn) == ["partition.drop_attempt", "partition.drop"]
    details = [p[3] for sql, p in conn.cur.executed if sql.startswith("INSERT INTO audit_log")]
    assert details == ["rows=7", "rows=7"]


def test_missing_catch_all_partition_is_an_error():
    conn = FakeConn(["p2026_11", "p2026_12"])
    with pytest.raises(PartitionError):
        maintain(conn, today=TODAY, retain_months=12)
