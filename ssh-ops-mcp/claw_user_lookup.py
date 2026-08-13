"""Read-only claw-auth user role lookup for ssh-ops RBAC."""

from __future__ import annotations

import os
import sqlite3
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


_ROLE_CACHE: dict[str, str | None] = {}


def lookup_role(username: str | None) -> str | None:
    """Return role for username from claw-auth SQLite, or None if unknown."""
    user = (username or "").strip().lower()
    if not user:
        return None
    if user in _ROLE_CACHE:
        return _ROLE_CACHE[user]
    role: str | None = None
    conn = _connect()
    if conn is not None:
        try:
            row = conn.execute(
                "SELECT role, disabled FROM users WHERE username = ?",
                (user,),
            ).fetchone()
            if row and not row["disabled"]:
                role = str(row["role"] or "").strip().lower() or None
        except sqlite3.Error:
            role = None
        finally:
            conn.close()
    _ROLE_CACHE[user] = role
    return role


def clear_role_cache() -> None:
    _ROLE_CACHE.clear()
    _EMAIL_CACHE.clear()


_EMAIL_CACHE: dict[str, str | None] = {}


def lookup_username_by_webex_email(email: str | None) -> str | None:
    """Map Webex personEmail to claw-auth username."""
    normalized = (email or "").strip().lower()
    if not normalized:
        return None
    if normalized in _EMAIL_CACHE:
        return _EMAIL_CACHE[normalized]
    username: str | None = None
    conn = _connect()
    if conn is not None:
        try:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
            if "webex_email" in cols:
                row = conn.execute(
                    """
                    SELECT username FROM users
                    WHERE webex_email = ? AND disabled = 0
                    """,
                    (normalized,),
                ).fetchone()
                if row:
                    username = str(row["username"])
        except sqlite3.Error:
            username = None
        finally:
            conn.close()
    _EMAIL_CACHE[normalized] = username
    return username
