#!/usr/bin/env python3
"""SQLite user and session store for claw-auth."""

from __future__ import annotations

import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

CLAW_AUTH_HOME = Path(
    os.environ.get("CLAW_AUTH_HOME", Path.home() / ".claw-auth")
).expanduser()
DB_PATH = Path(os.environ.get("CLAW_AUTH_DB", CLAW_AUTH_HOME / "users.db")).expanduser()
SESSION_HOURS = int(os.environ.get("CLAW_AUTH_SESSION_HOURS", "24"))


def _connect() -> sqlite3.Connection:
    CLAW_AUTH_HOME.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'admin',
                created_at TEXT NOT NULL,
                disabled INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(username) REFERENCES users(username)
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_username ON sessions(username);
            """
        )
        try:
            os.chmod(DB_PATH, 0o600)
        except OSError:
            pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def create_user(username: str, password: str, role: str = "admin") -> None:
    username = username.strip().lower()
    if not username or not password:
        raise ValueError("username and password required")
    init_db()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO users (username, password_hash, role, created_at, disabled)
            VALUES (?, ?, ?, ?, 0)
            """,
            (
                username,
                generate_password_hash(password),
                role,
                _iso(_now()),
            ),
        )


def delete_user(username: str) -> None:
    username = username.strip().lower()
    with _connect() as conn:
        conn.execute("DELETE FROM sessions WHERE username = ?", (username,))
        conn.execute("DELETE FROM users WHERE username = ?", (username,))


def set_password(username: str, password: str) -> None:
    username = username.strip().lower()
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?",
            (generate_password_hash(password), username),
        )
        if cur.rowcount == 0:
            raise ValueError(f"user not found: {username}")


def authenticate(username: str, password: str) -> dict | None:
    username = username.strip().lower()
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT username, password_hash, role, disabled FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    if not row or row["disabled"]:
        return None
    if not check_password_hash(row["password_hash"], password):
        return None
    return {"username": row["username"], "role": row["role"]}


def create_session(username: str) -> str:
    token = secrets.token_urlsafe(32)
    expires = _now() + timedelta(hours=SESSION_HOURS)
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO sessions (token, username, expires_at, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (token, username, _iso(expires), _iso(_now())),
        )
    return token


def delete_session(token: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def get_session(token: str | None) -> dict | None:
    if not token:
        return None
    init_db()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT s.token, s.username, s.expires_at, u.role, u.disabled
            FROM sessions s
            JOIN users u ON u.username = s.username
            WHERE s.token = ?
            """,
            (token,),
        ).fetchone()
    if not row or row["disabled"]:
        return None
    expires = datetime.fromisoformat(row["expires_at"])
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= _now():
        delete_session(token)
        return None
    return {
        "username": row["username"],
        "role": row["role"],
        "token": row["token"],
    }


def list_users() -> list[dict]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT username, role, created_at, disabled FROM users ORDER BY username"
        ).fetchall()
    return [dict(row) for row in rows]


def purge_expired_sessions() -> int:
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM sessions WHERE expires_at <= ?",
            (_iso(_now()),),
        )
        return cur.rowcount


def user_count() -> int:
    init_db()
    with _connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()
    return int(row["n"]) if row else 0
