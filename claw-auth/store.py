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
            CREATE TABLE IF NOT EXISTS mcp_binds (
                token TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(username) REFERENCES users(username)
            );
            CREATE INDEX IF NOT EXISTS idx_mcp_binds_username ON mcp_binds(username);
            CREATE TABLE IF NOT EXISTS mcp_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                label TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                expires_at TEXT,
                last_used_at TEXT,
                revoked INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(username) REFERENCES users(username)
            );
            CREATE INDEX IF NOT EXISTS idx_mcp_tokens_username ON mcp_tokens(username);
            CREATE INDEX IF NOT EXISTS idx_mcp_tokens_hash ON mcp_tokens(token_hash);
            """
        )
        try:
            os.chmod(DB_PATH, 0o600)
        except OSError:
            pass
        _migrate_webex_email(conn)


def _migrate_webex_email(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
    if "webex_email" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN webex_email TEXT")
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_webex_email
            ON users(webex_email)
            WHERE webex_email IS NOT NULL AND webex_email != ''
            """
        )


def _norm_email(email: str | None) -> str:
    return (email or "").strip().lower()


VALID_ROLES = frozenset({"admin", "operator"})


def _norm_role(role: str | None) -> str:
    normalized = (role or "").strip().lower()
    if normalized not in VALID_ROLES:
        raise ValueError(f"invalid role: {role!r} (allowed: admin, operator)")
    return normalized


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def create_user(username: str, password: str, role: str = "admin") -> None:
    username = username.strip().lower()
    if not username or not password:
        raise ValueError("username and password required")
    role = _norm_role(role)
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
            """
            SELECT username, role, created_at, disabled, webex_email
            FROM users ORDER BY username
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_user(username: str) -> dict | None:
    username = username.strip().lower()
    if not username:
        return None
    init_db()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT username, role, created_at, disabled, webex_email
            FROM users WHERE username = ?
            """,
            (username,),
        ).fetchone()
    return dict(row) if row else None


def admin_count(*, include_disabled: bool = False) -> int:
    init_db()
    with _connect() as conn:
        if include_disabled:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM users WHERE role = 'admin'"
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND disabled = 0"
            ).fetchone()
    return int(row["n"]) if row else 0


def update_user(
    username: str,
    *,
    role: str | None = None,
    password: str | None = None,
    webex_email: str | None = None,
    disabled: bool | None = None,
    actor: str | None = None,
) -> None:
    """Update user fields. Password is changed only when non-empty."""
    username = username.strip().lower()
    actor = (actor or "").strip().lower()
    if not get_user(username):
        raise ValueError(f"user not found: {username}")

    if role is not None:
        role = _norm_role(role)
        current = get_user(username)
        if (
            current
            and current["role"] == "admin"
            and role != "admin"
            and admin_count(include_disabled=False) <= 1
        ):
            raise ValueError("cannot demote the last active admin")
        if actor and actor == username and role != "admin":
            raise ValueError("cannot remove your own admin role")
        with _connect() as conn:
            conn.execute(
                "UPDATE users SET role = ? WHERE username = ?",
                (role, username),
            )

    if password:
        set_password(username, password)

    if webex_email is not None:
        set_webex_email(username, webex_email)

    if disabled is not None:
        if actor and actor == username and disabled:
            raise ValueError("cannot disable your own account")
        if disabled and get_user(username) and get_user(username)["role"] == "admin":
            if admin_count(include_disabled=False) <= 1:
                raise ValueError("cannot disable the last active admin")
        with _connect() as conn:
            conn.execute(
                "UPDATE users SET disabled = ? WHERE username = ?",
                (1 if disabled else 0, username),
            )
            if disabled:
                conn.execute("DELETE FROM sessions WHERE username = ?", (username,))


def set_webex_email(username: str, email: str | None) -> None:
    username = username.strip().lower()
    normalized = _norm_email(email)
    init_db()
    with _connect() as conn:
        if normalized:
            existing = conn.execute(
                """
                SELECT username FROM users
                WHERE webex_email = ? AND username != ?
                """,
                (normalized, username),
            ).fetchone()
            if existing:
                raise ValueError(
                    f"Webex email already linked to user '{existing['username']}'"
                )
        cur = conn.execute(
            "UPDATE users SET webex_email = ? WHERE username = ?",
            (normalized or None, username),
        )
        if cur.rowcount == 0:
            raise ValueError(f"user not found: {username}")


def get_user_by_webex_email(email: str | None) -> dict | None:
    normalized = _norm_email(email)
    if not normalized:
        return None
    init_db()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT username, role, disabled, webex_email
            FROM users WHERE webex_email = ?
            """,
            (normalized,),
        ).fetchone()
    if not row or row["disabled"]:
        return None
    return {
        "username": row["username"],
        "role": row["role"],
        "webex_email": row["webex_email"],
    }


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


def get_user_role(username: str) -> str | None:
    username = username.strip().lower()
    if not username:
        return None
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT role, disabled FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    if not row or row["disabled"]:
        return None
    return str(row["role"] or "operator").strip().lower()


def purge_expired_mcp_binds() -> int:
    init_db()
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM mcp_binds WHERE expires_at <= ?",
            (_iso(_now()),),
        )
        return cur.rowcount


def create_mcp_bind(username: str, *, hours: int | None = None) -> str:
    """Issue a short-lived token for MCP identity binding (OpenClaw chat path)."""
    username = username.strip().lower()
    role = get_user_role(username)
    if not role:
        raise ValueError(f"unknown or disabled user: {username}")
    ttl_hours = hours if hours is not None else int(
        os.environ.get("CLAW_MCP_BIND_HOURS", "8")
    )
    token = secrets.token_urlsafe(32)
    expires = _now() + timedelta(hours=max(1, ttl_hours))
    purge_expired_mcp_binds()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO mcp_binds (token, username, expires_at, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (token, username, _iso(expires), _iso(_now())),
        )
    return token
