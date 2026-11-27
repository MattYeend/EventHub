"""Forward-only SQL migrations, applied by the application itself."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from importlib.resources import files

from .db import Connection, dict_cursor

LOCK_NAME = "eventhub_migrations"
LOCK_TIMEOUT_SECONDS = 30

_FILENAME = re.compile(r"(?P<version>\d{4})_(?P<name>[a-z0-9_]+)\.sql")
_SPLIT = re.compile(r"^-- split[ \t]*$", re.MULTILINE)


class MigrationError(RuntimeError):
    """Raised when migrations cannot be applied safely."""


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    checksum: str
    statements: tuple[str, ...]


def split_statements(text: str) -> tuple[str, ...]:
    """Split a migration file on '-- split' marker lines (one statement per chunk)."""
    chunks = (chunk.strip().rstrip(";").strip() for chunk in _SPLIT.split(text))
    return tuple(chunk for chunk in chunks if chunk)


def load_migrations() -> list[Migration]:
    migrations: list[Migration] = []
    for entry in files("eventhub").joinpath("migrations").iterdir():
        match = _FILENAME.fullmatch(entry.name)
        if match is None:
            continue
        text = entry.read_text(encoding="utf-8").replace("\r\n", "\n")
        migrations.append(
            Migration(
                version=int(match["version"]),
                name=match["name"],
                checksum=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                statements=split_statements(text),
            )
        )
    return sorted(migrations, key=lambda m: m.version)


def apply_migrations(conn: Connection) -> list[str]:
    """Apply pending migrations in order and return their names.

    A named lock stops two instances migrating at once. A changed checksum on an
    already-applied migration aborts, because history must never be edited.
    MySQL DDL commits implicitly, so each file is applied statement by statement.
    """
    applied_now: list[str] = []
    with dict_cursor(conn) as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version    INT UNSIGNED NOT NULL,"
            " name       VARCHAR(100) NOT NULL,"
            " checksum   CHAR(64)     NOT NULL,"
            " applied_at DATETIME     NOT NULL DEFAULT (UTC_TIMESTAMP()),"
            " PRIMARY KEY (version)"
            ") ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci"
        )
        cur.execute("SELECT GET_LOCK(%s, %s) AS got", (LOCK_NAME, LOCK_TIMEOUT_SECONDS))
        row = cur.fetchone()
        if not row or row["got"] != 1:
            raise MigrationError("Could not obtain the migration lock")
        try:
            cur.execute("SELECT version, checksum FROM schema_migrations")
            applied = {int(r["version"]): r["checksum"] for r in cur.fetchall()}
            for migration in load_migrations():
                recorded = applied.get(migration.version)
                if recorded is not None:
                    if recorded != migration.checksum:
                        raise MigrationError(
                            f"Migration {migration.version:04d} was modified after being applied"
                        )
                    continue
                for statement in migration.statements:
                    cur.execute(statement)
                cur.execute(
                    "INSERT INTO schema_migrations (version, name, checksum) VALUES (%s, %s, %s)",
                    (migration.version, migration.name, migration.checksum),
                )
                conn.commit()
                applied_now.append(f"{migration.version:04d}_{migration.name}")
        finally:
            cur.execute("SELECT RELEASE_LOCK(%s) AS released", (LOCK_NAME,))
            cur.fetchall()
    return applied_now
