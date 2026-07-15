"""Resolve who initiated a change (portal user, MCP header, or explicit param)."""

from __future__ import annotations

import contextvars
import os

# Set per HTTP request by MCP bearer middleware (streamable-http / sse).
_request_actor: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "ssh_ops_request_actor",
    default=None,
)


def set_request_actor(username: str | None) -> None:
    _request_actor.set((username or "").strip() or None)


def resolve_actor(explicit: str | None = None, *, default: str = "agent") -> str:
    """Best-effort actor for audit/approval records."""
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    ctx = _request_actor.get()
    if ctx:
        return ctx
    env = (os.environ.get("SSH_OPS_DEFAULT_ACTOR") or "").strip()
    if env:
        return env
    return default


def actor_from_headers(headers: dict[str, str]) -> str | None:
    for key in (
        "X-Auth-User",
        "X-OpenClaw-User",
        "X-Claw-User",
        "X-Forwarded-User",
    ):
        val = (headers.get(key) or headers.get(key.lower()) or "").strip()
        if val:
            return val
    return None
