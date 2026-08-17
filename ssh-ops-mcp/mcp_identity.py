"""Shared MCP identity resolution (PAT, bind token, trusted proxy)."""

from __future__ import annotations

import os
from dataclasses import dataclass

import change_actor
import mcp_bind
import mcp_tokens
from claw_user_lookup import lookup_role

_STRIP_HEADERS = frozenset({
    "x-auth-user",
    "x-auth-role",
    "x-forwarded-user",
    "x-openclaw-user",
    "x-claw-user",
    "x-openclaw-role",
    "x-claw-role",
})


@dataclass
class IdentityResult:
    username: str | None = None
    role: str | None = None
    invalid_token: bool = False


def trusted_proxy_ips() -> frozenset[str]:
    raw = (os.environ.get("SSH_OPS_TRUSTED_PROXY_IPS") or "").strip()
    if not raw:
        return frozenset()
    return frozenset(ip.strip() for ip in raw.split(",") if ip.strip())


def bearer_token(headers: dict[str, str]) -> str:
    hdr = (
        headers.get("Authorization")
        or headers.get("authorization")
        or ""
    ).strip()
    if hdr.lower().startswith("bearer "):
        return hdr[7:].strip()
    # Some MCP clients (mcp-remote) send the raw token without a Bearer prefix.
    if hdr.startswith(mcp_tokens.PAT_PREFIX):
        return hdr
    return ""


def strip_client_identity(headers: dict[str, str]) -> dict[str, str]:
    return {
        k: v
        for k, v in headers.items()
        if k.lower() not in _STRIP_HEADERS
    }


def resolve_identity(
    headers: dict[str, str],
    *,
    peer_ip: str | None = None,
) -> IdentityResult:
    """First match wins: PAT, bind token, trusted-proxy headers, anonymous."""
    token = bearer_token(headers)
    if token.startswith(mcp_tokens.PAT_PREFIX):
        pat = mcp_tokens.validate_pat(token)
        if pat:
            return IdentityResult(pat["username"], pat["role"])
        return IdentityResult(invalid_token=True)

    bind_hdr = (
        headers.get("X-Claw-Mcp-Bind")
        or headers.get("x-claw-mcp-bind")
        or ""
    ).strip()
    if bind_hdr:
        bound = mcp_bind.validate_bind_token(bind_hdr)
        if bound:
            return IdentityResult(bound["username"], bound["role"])

    peer = (peer_ip or "").strip()
    if peer and peer in trusted_proxy_ips():
        user = change_actor.actor_from_headers(headers)
        role = change_actor.role_from_headers(headers)
        if user and not role:
            role = lookup_role(user)
        if user:
            return IdentityResult(user, role)

    return IdentityResult()


def apply_identity(result: IdentityResult) -> None:
    change_actor.set_request_identity(result.username, result.role)
