"""Personal access tokens (PATs) for universal MCP Bearer auth."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("ssh_ops.mcp_tokens")

PAT_PREFIX = "skops_"
CLAW_AUTH_DB = Path(
    os.environ.get("CLAW_AUTH_DB", Path.home() / ".claw-auth" / "users.db")
).expanduser()


def _db_path() -> Path:
    return Path(os.environ.get("CLAW_AUTH_DB", str(CLAW_AUTH_DB))).expanduser()


def _connect(*, write: bool = False) -> sqlite3.Connection | None:
    path = _db_path()
    if not path.is_file():
        return None
    try:
        mode = "rw" if write else "ro"
        conn = sqlite3.connect(f"file:{path}?mode={mode}", uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error:
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def ensure_schema() -> None:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
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
            os.chmod(path, 0o600)
        except OSError:
            pass


def _token_prefix(raw: str) -> str:
    return raw[:10] if len(raw) >= 10 else raw[: len(raw)]


def _touch_pat_last_used(token_id: int) -> None:
    """Best-effort audit update; ignored when DB is read-only (MCP container)."""
    conn = _connect(write=True)
    if conn is None:
        return
    try:
        conn.execute(
            "UPDATE mcp_tokens SET last_used_at = ? WHERE id = ?",
            (_iso(_now()), int(token_id)),
        )
        conn.commit()
    except sqlite3.Error:
        pass
    finally:
        conn.close()


def validate_pat(raw: str | None) -> dict | None:
    """Return {username, role} when PAT is valid."""
    token = (raw or "").strip()
    if not token.startswith(PAT_PREFIX):
        return None
    if not _db_path().is_file():
        return None
    try:
        ensure_schema()
    except (sqlite3.Error, OSError):
        pass
    conn = _connect(write=False)
    if conn is None:
        return None
    try:
        row = conn.execute(
            """
            SELECT t.id, t.username, t.expires_at, t.revoked, u.role, u.disabled
            FROM mcp_tokens t
            JOIN users u ON u.username = t.username
            WHERE t.token_hash = ?
            """,
            (_hash_token(token),),
        ).fetchone()
        if not row or row["disabled"] or row["revoked"]:
            log.info("pat_reject prefix=%s reason=missing_or_revoked", _token_prefix(token))
            return None
        if row["expires_at"]:
            expires = datetime.fromisoformat(row["expires_at"])
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires <= _now():
                log.info("pat_reject prefix=%s reason=expired", _token_prefix(token))
                return None
        identity = {
            "username": row["username"],
            "role": str(row["role"] or "operator").strip().lower(),
        }
        _touch_pat_last_used(row["id"])
        return identity
    except sqlite3.Error as exc:
        log.info("pat_reject prefix=%s reason=db_error detail=%s", _token_prefix(token), exc)
        return None
    finally:
        conn.close()


def issue_pat(
    username: str,
    label: str,
    *,
    ttl_days: int | None = None,
) -> str:
    """Create a PAT; returns raw token (shown once)."""
    username = username.strip().lower()
    label = (label or "").strip() or "MCP token"
    ensure_schema()
    conn = _connect(write=True)
    if conn is None:
        raise ValueError("claw-auth database unavailable")
    try:
        user = conn.execute(
            "SELECT username, disabled FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if not user or user["disabled"]:
            raise ValueError(f"unknown or disabled user: {username}")
        raw = PAT_PREFIX + secrets.token_urlsafe(32)
        expires_at = None
        if ttl_days is not None and ttl_days > 0:
            expires_at = _iso(_now() + timedelta(days=int(ttl_days)))
        conn.execute(
            """
            INSERT INTO mcp_tokens
                (username, token_hash, label, created_at, expires_at, revoked)
            VALUES (?, ?, ?, ?, ?, 0)
            """,
            (
                username,
                _hash_token(raw),
                label,
                _iso(_now()),
                expires_at,
            ),
        )
        conn.commit()
        return raw
    finally:
        conn.close()


def list_pats(username: str) -> list[dict]:
    username = username.strip().lower()
    ensure_schema()
    conn = _connect()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            """
            SELECT id, username, label, created_at, expires_at, last_used_at, revoked
            FROM mcp_tokens
            WHERE username = ?
            ORDER BY created_at DESC
            """,
            (username,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_pat(token_id: int) -> dict | None:
    ensure_schema()
    conn = _connect()
    if conn is None:
        return None
    try:
        row = conn.execute(
            """
            SELECT id, username, label, created_at, expires_at, last_used_at, revoked
            FROM mcp_tokens WHERE id = ?
            """,
            (int(token_id),),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_all_pats() -> list[dict]:
    ensure_schema()
    conn = _connect()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            """
            SELECT id, username, label, created_at, expires_at, last_used_at, revoked
            FROM mcp_tokens
            ORDER BY username, created_at DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def revoke_pat(token_id: int, *, actor: str, is_superadmin: bool = False) -> None:
    ensure_schema()
    conn = _connect(write=True)
    if conn is None:
        raise ValueError("claw-auth database unavailable")
    try:
        row = conn.execute(
            "SELECT id, username, revoked FROM mcp_tokens WHERE id = ?",
            (int(token_id),),
        ).fetchone()
        if not row:
            raise ValueError(f"token not found: {token_id}")
        if not is_superadmin and row["username"] != actor.strip().lower():
            raise ValueError("forbidden")
        if row["revoked"]:
            return
        conn.execute(
            "UPDATE mcp_tokens SET revoked = 1 WHERE id = ?",
            (int(token_id),),
        )
        conn.commit()
    finally:
        conn.close()
