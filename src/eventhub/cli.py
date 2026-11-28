"""Command line entry point: apply migrations and bootstrap the first administrator."""

from __future__ import annotations

import argparse
import getpass
import sys

from dotenv import load_dotenv
from mysql.connector import errorcode, errors

from .accounts import (
    DuplicateUserError,
    InvalidUsernameError,
    Role,
    create_user,
)
from .config import AppConfig, ConfigError
from .db import get_connection, init_pool
from .migrate import MigrationError, apply_migrations
from .security import PasswordPolicyError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="eventhub")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="Apply pending database migrations")
    admin = sub.add_parser("create-admin", help="Create an administrator account")
    admin.add_argument("--username", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    load_dotenv()  # does not override variables that are already set
    try:
        config = AppConfig.from_env()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    init_pool(config.db)

    if args.command == "migrate":
        try:
            with get_connection() as conn:
                applied = apply_migrations(conn)
        except MigrationError as exc:
            print(f"Migration failed: {exc}", file=sys.stderr)
            return 1
        print("Applied: " + ", ".join(applied) if applied else "Database is up to date")
        return 0

    # The password is read from the terminal only, never from arguments or the environment.
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Confirm password: "):
        print("Passwords do not match", file=sys.stderr, flush=True)
        return 1
    try:
        with get_connection() as conn:
            user = create_user(
                conn, args.username, password, Role.ADMIN, must_change_password=False
            )
    except (InvalidUsernameError, PasswordPolicyError, DuplicateUserError) as exc:
        print(f"Could not create administrator: {exc}", file=sys.stderr, flush=True)
        return 1
    except errors.ProgrammingError as exc:
        if exc.errno != errorcode.ER_NO_SUCH_TABLE:
            raise
        print("Database is not ready. Run 'eventhub migrate' first", file=sys.stderr)
        return 1
    print(f"Created administrator '{user.username}' (id {user.id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
