#!/usr/bin/env python3
"""
MCP identity proxy — inject verified claw-auth user/role before ssh-ops MCP.

OpenClaw (or other clients) point at this proxy instead of :8766 directly.
The proxy validates Bearer PATs (skops_…), shared MCP tokens, or
X-Claw-Mcp-Bind, and forwards trusted X-Auth-User / X-Auth-Role headers to
the upstream MCP server. Client-supplied identity headers are stripped unless
the peer is in SSH_OPS_TRUSTED_PROXY_IPS.

Run:
    export CLAW_AUTH_DB=~/.claw-auth/users.db
    export SSH_OPS_MCP_UPSTREAM=https://127.0.0.1:8766
    python mcp_identity_proxy.py
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mcp_identity
import mcp_tokens
import secrets_store

log = logging.getLogger("ssh_ops.mcp_identity_proxy")

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


def _peer_ip(request: Request) -> str:
    forwarded = (request.headers.get("X-Real-IP") or "").strip()
    if forwarded:
        return forwarded
    client = request.client
    return client.host if client else ""


def _upstream_bearer() -> str:
    secrets_store.ensure_mcp_token()
    tokens = secrets_store.get_mcp_tokens()
    return next(iter(tokens), "")


class IdentityProxyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/.well-known/oauth-protected-resource":
            return await call_next(request)

        auth_on = os.environ.get("SSH_OPS_MCP_AUTH", "1").lower() not in (
            "0",
            "false",
            "no",
            "off",
            "",
        )
        bearer = mcp_identity.bearer_token(dict(request.headers))

        if bearer.startswith(mcp_tokens.PAT_PREFIX):
            result = mcp_identity.resolve_identity(
                dict(request.headers),
                peer_ip=_peer_ip(request),
            )
            if result.invalid_token:
                log.info("auth_fail reason=invalid_pat prefix=%s", bearer[:10])
                return JSONResponse(
                    {"error": "invalid or expired token", "code": "invalid_token"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
            request.state.mcp_identity = result
            return await call_next(request)

        if auth_on:
            secrets_store.ensure_mcp_token()
            if not bearer or bearer not in secrets_store.get_mcp_tokens():
                return JSONResponse(
                    {"error": "unauthorized"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
        return await call_next(request)


async def _oauth_discovery(_request: Request) -> Response:
    # TODO: MCP OAuth 2.1 authorization spec — protected resource metadata here.
    return JSONResponse({"error": "not implemented"}, status_code=404)


async def _proxy(request: Request) -> Response:
    path = request.url.path.lstrip("/")
    upstream_url = f"{UPSTREAM}/{path}" if path else UPSTREAM
    if request.url.query:
        upstream_url = f"{upstream_url}?{request.url.query}"

    original = dict(request.headers)
    headers = mcp_identity.strip_client_identity(original)
    headers.pop("host", None)

    if getattr(request.state, "mcp_identity", None) is not None:
        ident = request.state.mcp_identity
    else:
        ident = mcp_identity.resolve_identity(original, peer_ip=_peer_ip(request))
        if ident.invalid_token:
            return JSONResponse(
                {"error": "invalid or expired token", "code": "invalid_token"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

    if ident.username:
        headers["X-Auth-User"] = ident.username
        headers["X-Forwarded-User"] = ident.username
    if ident.role:
        headers["X-Auth-Role"] = ident.role

    client_bearer = mcp_identity.bearer_token(original)
    # Forward skops_ PATs to upstream so :8766 validates proposer identity.
    # Replacing PAT with the shared bearer drops user identity (propose_change fails).
    if not client_bearer.startswith(mcp_tokens.PAT_PREFIX):
        if not mcp_identity.bearer_token(headers) and _upstream_bearer():
            headers["Authorization"] = f"Bearer {_upstream_bearer()}"
    bind_hdr = (
        original.get("X-Claw-Mcp-Bind")
        or original.get("x-claw-mcp-bind")
        or ""
    ).strip()
    if bind_hdr:
        headers["X-Claw-Mcp-Bind"] = bind_hdr

    body = await request.body()
    try:
        async with httpx.AsyncClient(verify=VERIFY_TLS, timeout=120.0) as client:
            upstream = await client.request(
                request.method,
                upstream_url,
                headers=headers,
                content=body,
            )
    except httpx.HTTPError as exc:
        log.warning("upstream request failed url=%s err=%s", upstream_url, exc)
        return JSONResponse(
            {"error": "upstream unavailable", "detail": str(exc)},
            status_code=502,
        )
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=dict(upstream.headers),
        media_type=upstream.headers.get("content-type"),
    )


app = Starlette()
app.add_middleware(IdentityProxyMiddleware)
app.add_route(
    "/.well-known/oauth-protected-resource",
    _oauth_discovery,
    methods=["GET"],
)
app.add_route("/{path:path}", _proxy, methods=["GET", "POST", "DELETE", "OPTIONS"])
app.add_route("/", _proxy, methods=["GET", "POST", "DELETE", "OPTIONS"])


def main() -> None:
    run_kw: dict[str, object] = {
        "host": LISTEN_HOST,
        "port": LISTEN_PORT,
        "log_level": "info",
    }
    tls_cert = os.environ.get("SSH_OPS_MCP_PROXY_TLS_CERT", "").strip()
    tls_key = os.environ.get("SSH_OPS_MCP_PROXY_TLS_KEY", "").strip()
    scheme = "http"
    if tls_cert and tls_key:
        run_kw["ssl_certfile"] = tls_cert
        run_kw["ssl_keyfile"] = tls_key
        scheme = "https"
    print(f"MCP identity proxy listening on {scheme}://{LISTEN_HOST}:{LISTEN_PORT}")
    print(f"Upstream: {UPSTREAM} (verify_tls={VERIFY_TLS})")
    if tls_cert:
        print(f"TLS cert: {tls_cert}")
    uvicorn.run(app, **run_kw)


if __name__ == "__main__":
    main()
