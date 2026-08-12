#!/usr/bin/env python3
"""
MCP identity proxy — inject verified claw-auth user/role before ssh-ops MCP.

OpenClaw (or other clients) point at this proxy instead of :8766 directly.
The proxy validates the shared MCP bearer token, optionally validates
X-Claw-Mcp-Bind (issued by claw-auth /mcp/bind), and forwards trusted
X-Auth-User / X-Auth-Role headers to the upstream MCP server.

Run:
    export CLAW_AUTH_DB=~/.claw-auth/users.db
    export SSH_OPS_MCP_UPSTREAM=https://127.0.0.1:8766
    python mcp_identity_proxy.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# Allow imports from this package when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import change_actor
import mcp_bind
import secrets_store
from claw_user_lookup import lookup_role

UPSTREAM = os.environ.get(
    "SSH_OPS_MCP_UPSTREAM", "https://192.168.1.10:8766"
).rstrip("/")
LISTEN_HOST = os.environ.get("SSH_OPS_MCP_PROXY_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("SSH_OPS_MCP_PROXY_PORT", "8767"))
VERIFY_TLS = os.environ.get("SSH_OPS_MCP_PROXY_VERIFY_TLS", "0").lower() in (
    "1",
    "true",
    "yes",
    "on",
)


def _resolve_identity(headers: dict[str, str]) -> tuple[str | None, str | None]:
    user = change_actor.actor_from_headers(headers)
    role = change_actor.role_from_headers(headers)
    bind_hdr = (
        headers.get("X-Claw-Mcp-Bind")
        or headers.get("x-claw-mcp-bind")
        or ""
    ).strip()
    if bind_hdr:
        bound = mcp_bind.validate_bind_token(bind_hdr)
        if bound:
            user = bound["username"]
            role = bound["role"]
    if user and not role:
        role = lookup_role(user)
    return user, role


class IdentityProxyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        auth_on = os.environ.get("SSH_OPS_MCP_AUTH", "1").lower() not in (
            "0",
            "false",
            "no",
            "off",
            "",
        )
        hdr = request.headers.get("authorization", "")
        tok = hdr[7:].strip() if hdr[:7].lower() == "bearer " else ""
        if auth_on:
            secrets_store.ensure_mcp_token()
            if not tok or tok not in secrets_store.get_mcp_tokens():
                return JSONResponse(
                    {"error": "unauthorized"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
        return await call_next(request)


async def _proxy(request: Request) -> Response:
    path = request.url.path.lstrip("/")
    upstream_url = f"{UPSTREAM}/{path}" if path else UPSTREAM
    if request.url.query:
        upstream_url = f"{upstream_url}?{request.url.query}"

    headers = dict(request.headers)
    headers.pop("host", None)
    user, role = _resolve_identity(headers)
    if user:
        headers["X-Auth-User"] = user
        headers["X-Forwarded-User"] = user
    if role:
        headers["X-Auth-Role"] = role

    body = await request.body()
    async with httpx.AsyncClient(verify=VERIFY_TLS, timeout=120.0) as client:
        upstream = await client.request(
            request.method,
            upstream_url,
            headers=headers,
            content=body,
        )
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=dict(upstream.headers),
        media_type=upstream.headers.get("content-type"),
    )


app = Starlette()
app.add_middleware(IdentityProxyMiddleware)
app.add_route("/{path:path}", _proxy, methods=["GET", "POST", "DELETE", "OPTIONS"])
app.add_route("/", _proxy, methods=["GET", "POST", "DELETE", "OPTIONS"])


def main() -> None:
    print(f"MCP identity proxy listening on {LISTEN_HOST}:{LISTEN_PORT}")
    print(f"Upstream: {UPSTREAM} (verify_tls={VERIFY_TLS})")
    uvicorn.run(app, host=LISTEN_HOST, port=LISTEN_PORT, log_level="info")


if __name__ == "__main__":
    main()
