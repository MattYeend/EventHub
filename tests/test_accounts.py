from datetime import datetime, timedelta

import pytest

from eventhub import accounts
from eventhub.accounts import (
    LOCKOUT,
    AuthenticationError,
    InvalidUsernameError,
    Role,
    authenticate,
    normalise_username,
)
from eventhub.security import hash_password

NOW = datetime(2026, 11, 26, 12, 0, 0)
PASSWORD = "correct-horse-battery"


class ScriptedCursor:
    def __init__(self, row):
        self.row = row
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return self.row


class ScriptedConn:
    def __init__(self, row):
        self.cur = ScriptedCursor(row)
        self.commits = 0

    def cursor(self, **kwargs):
        return self.cur

    def commit(self):
        self.commits += 1


def make_row(**overrides):
    row = {
        "id": 7,
        "username": "alice",
        "password_hash": hash_password(PASSWORD),
        "role": "reporter",
        "is_active": 1,
        "must_change_password": 0,
        "failed_logins": 0,
        "locked_until": None,
    }
    row.update(overrides)
    return row


def counter_updates(conn):
    return [e for e in conn.cur.executed if e[0].startswith("UPDATE users SET failed_logins")]


@pytest.mark.parametrize("raw", ["  Alice.Smith ", "ADMIN", "a_b-c.d"])
def test_usernames_are_normalised(raw):
    assert normalise_username(raw) == raw.strip().lower()


@pytest.mark.parametrize("raw", ["ab", "has space", "semi;colon", "x" * 65, "", "caf\u00e9"])
def test_bad_usernames_are_rejected(raw):
    with pytest.raises(InvalidUsernameError):
        normalise_username(raw)


def test_unknown_role_is_rejected():
    with pytest.raises(ValueError):
        Role("superuser")


def test_update_requires_a_change():
    with pytest.raises(ValueError):
        accounts.update_user(None, 1)


def test_successful_login_resets_counters_and_returns_user():
    conn = ScriptedConn(make_row(failed_logins=3))
    user = authenticate(conn, "Alice", PASSWORD, now=NOW)
    assert user.username == "alice" and user.role is Role.REPORTER
    assert any("failed_logins = 0" in sql for sql, _ in conn.cur.executed)


def test_wrong_password_increments_the_counter_and_commits():
    conn = ScriptedConn(make_row(failed_logins=1))
    with pytest.raises(AuthenticationError):
        authenticate(conn, "alice", "wrong-password-value", now=NOW)
    assert counter_updates(conn)[0][1] == (2, None, 7)
    assert conn.commits == 1


def test_fifth_failure_locks_the_account():
    conn = ScriptedConn(make_row(failed_logins=4))
    with pytest.raises(AuthenticationError):
        authenticate(conn, "alice", "wrong-password-value", now=NOW)
    assert counter_updates(conn)[0][1] == (0, NOW + LOCKOUT, 7)


def test_locked_account_rejects_the_correct_password():
    conn = ScriptedConn(make_row(locked_until=NOW + timedelta(minutes=1)))
    with pytest.raises(AuthenticationError):
        authenticate(conn, "alice", PASSWORD, now=NOW)
    assert counter_updates(conn) == []


def test_inactive_account_is_rejected():
    conn = ScriptedConn(make_row(is_active=0))
    with pytest.raises(AuthenticationError):
        authenticate(conn, "alice", PASSWORD, now=NOW)


def test_unknown_user_gets_the_same_generic_error():
    conn = ScriptedConn(None)
    with pytest.raises(AuthenticationError):
        authenticate(conn, "nobody", PASSWORD, now=NOW)
    assert conn.commits == 1