"""User accounts, sessions and authentication."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, NoReturn

from mysql.connector import errorcode, errors

from . import audit
from .db import Connection, dict_cursor
from .security import (
    DUMMY_HASH,
    hash_password,
    hash_token,
    needs_rehash,
    new_session_token,
    utcnow,
    validate_password,
    verify_password,
)

MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=15)
MAX_LIST_LIMIT = 200

_USERNAME = re.compile(r"[a-z0-9._-]{3,64}")


class Role(StrEnum):
    ADMIN = "admin"
    INGEST = "ingest"
    REPORTER = "reporter"


class AuthenticationError(Exception):
    """Credentials were not accepted. Deliberately gives no reason to the caller."""


class DuplicateUserError(Exception):
    """The username is already taken."""


class UserNotFoundError(LookupError):
    """No user exists with the given id."""


class LastAdminError(Exception):
    """The change would leave the system without an active administrator."""


class InvalidUsernameError(ValueError):
    """The username does not match the allowed format."""


@dataclass(frozen=True, slots=True)
class User:
    id: int
    username: str
    role: Role
    is_active: bool
    must_change_password: bool


def _row_to_user(row: Mapping[str, Any]) -> User:
    return User(
        id=int(row["id"]),
        username=str(row["username"]),
        role=Role(row["role"]),
        is_active=bool(row["is_active"]),
        must_change_password=bool(row["must_change_password"]),
    )


def normalise_username(raw: str) -> str:
    name = raw.strip().lower()
    if not _USERNAME.fullmatch(name):
        raise InvalidUsernameError(
            "Username must be 3 to 64 characters using a-z, 0-9, dot, underscore or hyphen"
        )
    return name


# ---------------------------------------------------------------- user management


def create_user(
    conn: Connection,
    username: str,
    password: str,
    role: Role,
    *,
    actor_id: int | None = None,
    must_change_password: bool = True,
) -> User:
    name = normalise_username(username)
    validate_password(password, name)
    role = Role(role)  # rejects unknown values
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (username, password_hash, role, must_change_password) "
                "VALUES (%s, %s, %s, %s)",
                (name, hash_password(password), role.value, int(must_change_password)),
            )
            user_id = int(cur.lastrowid)
    except errors.IntegrityError as exc:
        if exc.errno == errorcode.ER_DUP_ENTRY:
            raise DuplicateUserError(name) from exc
        raise
    audit.record(
        conn,
        "user.create",
        actor_id=actor_id,
        target=f"user:{user_id}",
        detail=f"role={role.value}",
    )
    return User(user_id, name, role, True, must_change_password)


def get_user(conn: Connection, user_id: int) -> User | None:
    with dict_cursor(conn) as cur:
        cur.execute(
            "SELECT id, username, role, is_active, must_change_password FROM users WHERE id = %s",
            (int(user_id),),
        )
        row = cur.fetchone()
    return None if row is None else _row_to_user(row)


def list_users(conn: Connection, limit: int = 50, offset: int = 0) -> list[User]:
    limit = max(1, min(int(limit), MAX_LIST_LIMIT))
    offset = max(0, int(offset))
    with dict_cursor(conn) as cur:
        cur.execute(
            "SELECT id, username, role, is_active, must_change_password FROM users "
            "ORDER BY id LIMIT %s OFFSET %s",
            (limit, offset),
        )
        return [_row_to_user(row) for row in cur.fetchall()]


def update_user(
    conn: Connection,
    user_id: int,
    *,
    role: Role | None = None,
    is_active: bool | None = None,
    actor_id: int | None = None,
) -> User:
    """Change a user's role or active flag, never leaving the system without an admin."""
    if role is None and is_active is None:
        raise ValueError("Nothing to update")
    with dict_cursor(conn) as cur:
        cur.execute(
            "SELECT id, username, role, is_active, must_change_password "
            "FROM users WHERE id = %s FOR UPDATE",
            (int(user_id),),
        )
        row = cur.fetchone()
        if row is None:
            raise UserNotFoundError(user_id)
        current = _row_to_user(row)
        new_role = current.role if role is None else Role(role)
        new_active = current.is_active if is_active is None else bool(is_active)

        loses_admin = (
            current.role is Role.ADMIN
            and current.is_active
            and (new_role is not Role.ADMIN or not new_active)
        )
        if loses_admin:
            cur.execute(
                "SELECT id FROM users WHERE role = %s AND is_active = 1 FOR UPDATE",
                (Role.ADMIN.value,),
            )
            if len(cur.fetchall()) <= 1:
                raise LastAdminError(user_id)

        cur.execute(
            "UPDATE users SET role = %s, is_active = %s WHERE id = %s",
            (new_role.value, int(new_active), current.id),
        )
    if not new_active:
        revoke_all_sessions(conn, current.id, utcnow())
    audit.record(
        conn,
        "user.update",
        actor_id=actor_id,
        target=f"user:{current.id}",
        detail=f"role={new_role.value} active={int(new_active)}",
    )
    return User(current.id, current.username, new_role, new_active, current.must_change_password)


def set_password(
    conn: Connection,
    user_id: int,
    new_password: str,
    *,
    must_change: bool,
    actor_id: int | None,
    action: str,
) -> None:
    """Replace a password, unlock the account and revoke every existing session."""
    with dict_cursor(conn) as cur:
        cur.execute("SELECT username FROM users WHERE id = %s FOR UPDATE", (int(user_id),))
        row = cur.fetchone()
        if row is None:
            raise UserNotFoundError(user_id)
        validate_password(new_password, str(row["username"]))
        cur.execute(
            "UPDATE users SET password_hash = %s, must_change_password = %s, "
            "failed_logins = 0, locked_until = NULL WHERE id = %s",
            (hash_password(new_password), int(must_change), int(user_id)),
        )
    revoke_all_sessions(conn, int(user_id), utcnow())
    audit.record(conn, action, actor_id=actor_id, target=f"user:{int(user_id)}")


def change_own_password(
    conn: Connection,
    user: User,
    current_password: str,
    new_password: str,
    *,
    client_ip: str | None = None,
) -> None:
    """Re-authenticate (so guesses count towards lockout), then set the new password."""
    authenticate(
        conn,
        user.username,
        current_password,
        now=utcnow(),
        client_ip=client_ip,
        success_action="auth.reauthenticate",
    )
    set_password(
        conn,
        user.id,
        new_password,
        must_change=False,
        actor_id=user.id,
        action="user.password_change",
    )


# ---------------------------------------------------------------- authentication


def _fail(conn: Connection, reason: str, client_ip: str | None, actor_id: int | None) -> NoReturn:
    """Audit and commit a failed attempt (so counters survive), then reject generically."""
    audit.record(conn, "auth.login_failed", actor_id=actor_id, detail=reason, client_ip=client_ip)
    conn.commit()
    raise AuthenticationError


def authenticate(
    conn: Connection,
    username: str,
    password: str,
    *,
    now: datetime,
    client_ip: str | None = None,
    success_action: str = "auth.login",
) -> User:
    name = username.strip().lower()
    with dict_cursor(conn) as cur:
        cur.execute(
            "SELECT id, username, password_hash, role, is_active, must_change_password, "
            "failed_logins, locked_until FROM users WHERE username = %s FOR UPDATE",
            (name,),
        )
        row = cur.fetchone()
        if row is None:
            verify_password(DUMMY_HASH, password)  # equalise timing for unknown usernames
            _fail(conn, "unknown user", client_ip, None)

        user_id = int(row["id"])
        valid = verify_password(str(row["password_hash"]), password)
        if row["locked_until"] is not None and row["locked_until"] > now:
            _fail(conn, "account locked", client_ip, user_id)
        if not row["is_active"]:
            _fail(conn, "account inactive", client_ip, user_id)
        if not valid:
            failures = int(row["failed_logins"]) + 1
            lock_until = now + LOCKOUT if failures >= MAX_FAILED_LOGINS else None
            cur.execute(
                "UPDATE users SET failed_logins = %s, locked_until = %s WHERE id = %s",
                (0 if lock_until else failures, lock_until, user_id),
            )
            _fail(conn, "account locked now" if lock_until else "bad password", client_ip, user_id)

        cur.execute(
            "UPDATE users SET failed_logins = 0, locked_until = NULL WHERE id = %s", (user_id,)
        )
        if needs_rehash(str(row["password_hash"])):
            cur.execute(
                "UPDATE users SET password_hash = %s WHERE id = %s",
                (hash_password(password), user_id),
            )
    audit.record(conn, success_action, actor_id=user_id, client_ip=client_ip)
    return _row_to_user(row)


# ---------------------------------------------------------------- sessions


def create_session(
    conn: Connection, user_id: int, ttl: timedelta, now: datetime
) -> tuple[str, datetime]:
    """Create a session and return the raw token (shown once) and its expiry."""
    token = new_session_token()
    expires_at = now + ttl
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sessions (user_id, token_hash, expires_at) VALUES (%s, %s, %s)",
            (int(user_id), hash_token(token), expires_at),
        )
    return token, expires_at


def resolve_session(conn: Connection, token: str, now: datetime) -> User | None:
    """Return the active user for a live session token, otherwise None."""
    with dict_cursor(conn) as cur:
        cur.execute(
            "SELECT u.id, u.username, u.role, u.is_active, u.must_change_password "
            "FROM sessions AS s JOIN users AS u ON u.id = s.user_id "
            "WHERE s.token_hash = %s AND s.revoked_at IS NULL AND s.expires_at > %s "
            "AND u.is_active = 1",
            (hash_token(token), now),
        )
        row = cur.fetchone()
    return None if row is None else _row_to_user(row)


def revoke_session(conn: Connection, token: str, now: datetime) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sessions SET revoked_at = %s WHERE token_hash = %s AND revoked_at IS NULL",
            (now, hash_token(token)),
        )


def revoke_all_sessions(conn: Connection, user_id: int, now: datetime) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sessions SET revoked_at = %s WHERE user_id = %s AND revoked_at IS NULL",
            (now, int(user_id)),
        )