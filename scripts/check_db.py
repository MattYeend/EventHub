"""Local integration check: UTC, utf8mb4, TLS and rollback. Prints no credentials."""

from pathlib import Path

from dotenv import load_dotenv

from eventhub.config import AppConfig
from eventhub.db import dict_cursor, get_connection, init_pool

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
init_pool(AppConfig.from_env().db)

with get_connection() as conn:
    cur = dict_cursor(conn)
    cur.execute("SELECT @@session.time_zone AS tz, @@character_set_connection AS cs")
    print(cur.fetchone())
    cur.execute("SHOW SESSION STATUS LIKE 'Ssl_cipher'")
    print(cur.fetchone())
    cur.execute("CREATE TEMPORARY TABLE rollback_probe (id INT)")
    cur.execute("INSERT INTO rollback_probe VALUES (1)")

try:
    with get_connection() as conn:
        cur = dict_cursor(conn)
        cur.execute("CREATE TEMPORARY TABLE rollback_probe (id INT)")
        cur.execute("INSERT INTO rollback_probe VALUES (1)")
        raise RuntimeError("forced failure")
except RuntimeError:
    print("rollback path exercised")
