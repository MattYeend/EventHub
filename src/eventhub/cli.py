"""Command line entry point (migrations only; administrator bootstrap arrives in #4)."""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from .config import AppConfig, ConfigError
from .db import get_connection, init_pool
from .migrate import MigrationError, apply_migrations


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="eventhub")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="Apply pending database migrations")
    return parser


def main(argv: list[str] | None = None) -> int:
    _build_parser().parse_args(argv)
    load_dotenv()  # does not override variables that are already set
    try:
        config = AppConfig.from_env()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    init_pool(config.db)
    try:
        with get_connection() as conn:
            applied = apply_migrations(conn)
    except MigrationError as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        return 1
    print("Applied: " + ", ".join(applied) if applied else "Database is up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
