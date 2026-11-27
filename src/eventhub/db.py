"""Pooled, TLS-protected database access."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from mysql.connector.pooling import MySQLConnectionPool, PooledMySQLConnection

from .config import DbConfig

Connection = PooledMySQLConnection

_pool: MySQLConnectionPool | None = None
_pool_lock = threading.Lock()


def _pool_kwargs(config: DbConfig) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "host": config.host,
        "port": config.port,
        "user": config.user,
        "password": config.password,
        "database": config.database,
        "charset": "utf8mb4",
        "collation": "utf8mb4_0900_ai_ci",
        "autocommit": False,
        "connection_timeout": 10,
        "time_zone": "+00:00",
    }
    if config.ssl_verify:
        kwargs.update(ssl_ca=config.ssl_ca, ssl_verify_cert=True, ssl_verify_identity=True)
    else:
        # Development only (enforced in config.py): still encrypted, certificate not verified.
        kwargs.update(ssl_verify_cert=False, ssl_verify_identity=False)
    return kwargs


def init_pool(config: DbConfig) -> None:
    """Create the shared connection pool once per process."""
    global _pool  # noqa: PLW0603
    with _pool_lock:
        if _pool is None:
            _pool = MySQLConnectionPool(
                pool_name="eventhub",
                pool_size=config.pool_size,
                pool_reset_session=True,
                **_pool_kwargs(config),
            )


@contextmanager
def get_connection() -> Iterator[Connection]:
    """Yield a pooled connection; commit on success, roll back on error, always release."""
    if _pool is None:
        raise RuntimeError("Database pool has not been initialised")
    conn = _pool.get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()  # returns the connection to the pool


def dict_cursor(conn: Connection) -> Any:
    """Buffered dictionary cursor, so nested cursors never hit 'Unread result found'."""
    return conn.cursor(dictionary=True, buffered=True)
