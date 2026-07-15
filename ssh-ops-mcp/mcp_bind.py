"""Validate short-lived MCP identity bind tokens issued by claw-auth."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

CLAW_AUTH_DB = Path(
    os.environ.get("CLAW_AUTH_DB", Path.home() / ".claw-auth" / "users.db")
).expanduser()


def _db_path() -> Path:
    return Path(
        os.environ.get("CLAW_AUTH_DB", str(CLAW_AUTH_DB))
    ).expanduser()


def _connect() -> sqlite3.Connection | None:
    path = _db_path()
    if not path.is_file():
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error:
        return None


def validate_bind_token(token: str | None) -> dict | None:
    """Return {username, role} when token is valid and not expired."""
    raw = (token or "").strip()
    if not raw:
        return None
    conn = _connect()
    if conn is None:
        return None
    try:
        row = conn.execute(
            """
            SELECT b.username, u.role, b.expires_at, u.disabled
            FROM mcp_binds b
            JOIN users u ON u.username = b.username
            WHERE b.token = ?
            """,
            (raw,),
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    if not row or row["disabled"]:
        return None
    expires = datetime.fromisoformat(row["expires_at"])
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= datetime.now(timezone.utc):
        return None
    return {
        "username": row["username"],
        "role": str(row["role"] or "operator").strip().lower(),
    }
