"""Append-only audit trail for security-relevant actions (ISO 27001 A.8.15)."""

from __future__ import annotations

from .db import Connection
from .sanitise import clip

ACTION_MAX = 64
TARGET_MAX = 128
DETAIL_MAX = 500
IP_MAX = 45


def record(
    conn: Connection,
    action: str,
    *,
    actor_id: int | None = None,
    target: str | None = None,
    detail: str | None = None,
    client_ip: str | None = None,
) -> None:
    """Write one audit row inside the caller's transaction. Free text is sanitised."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO audit_log (actor_user_id, action, target, detail, client_ip) "
            "VALUES (%s, %s, %s, %s, %s)",
            (
                actor_id,
                clip(action, ACTION_MAX),
                clip(target, TARGET_MAX),
                clip(detail, DETAIL_MAX),
                clip(client_ip, IP_MAX),
            ),
        )
