"""Resolve who initiated a change (portal user, MCP header, or explicit param)."""

from __future__ import annotations

import contextvars
import os

# Set per HTTP request by MCP bearer middleware (streamable-http / sse).
_request_actor: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "ssh_ops_request_actor",
    default=None,
)
_request_role: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "ssh_ops_request_role",
    default=None,
)


class IdentityMismatch(ValueError):
    """Raised when LLM-supplied identity disagrees with verified headers."""

    code = "identity_mismatch"


def set_request_actor(username: str | None) -> None:
    _request_actor.set((username or "").strip() or None)


def set_request_role(role: str | None) -> None:
    _request_role.set((role or "").strip().lower() or None)


def set_request_identity(username: str | None, role: str | None = None) -> None:
    set_request_actor(username)
    set_request_role(role)


def _norm(user: str | None) -> str:
    return (user or "").strip().lower()


def resolve_actor(explicit: str | None = None, *, default: str = "agent") -> str:
    """Best-effort actor for audit/approval records.

    Verified HTTP identity (from portal/proxy headers) always wins over
    LLM-supplied ``requested_by``. A mismatch raises IdentityMismatch.
    """
    trusted = _request_actor.get()
    if trusted:
        if explicit and str(explicit).strip():
            exp = str(explicit).strip()
            if _norm(exp) != _norm(trusted):
                raise IdentityMismatch(
                    f"requested_by '{exp}' does not match verified user '{trusted}'."
                )
        return trusted
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    env = (os.environ.get("SSH_OPS_DEFAULT_ACTOR") or "").strip()
    if env:
        return env
    return default


def resolve_role(*, verify_username: str | None = None) -> str | None:
    """Role for the current request; header first, then claw-auth DB lookup."""
    header_role = _request_role.get()
    actor = verify_username or _request_actor.get()
    if header_role and actor:
        from claw_user_lookup import lookup_role

        db_role = lookup_role(actor)
        if db_role and _norm(db_role) != _norm(header_role):
            # Trust DB over spoofable header when both are present.
            return db_role
        return header_role
    if header_role:
        return header_role
    if actor:
        from claw_user_lookup import lookup_role

        return lookup_role(actor)
    return None


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


def role_from_headers(headers: dict[str, str]) -> str | None:
    for key in ("X-Auth-Role", "X-OpenClaw-Role", "X-Claw-Role"):
        val = (headers.get(key) or headers.get(key.lower()) or "").strip()
        if val:
            return val.lower()
    return None
