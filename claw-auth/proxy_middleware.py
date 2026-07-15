#!/usr/bin/env python3
"""
Proxy auth gate for clawlab Flask apps behind nginx + claw-auth.

When CLAW_AUTH_REQUIRED=1, only requests nginx authenticated (auth_request)
are allowed — identified by X-Auth-User / X-Forwarded-User headers.
"""

from __future__ import annotations

import os

from flask import abort, request

AUTH_ENABLED = os.environ.get("CLAW_AUTH_REQUIRED", "0").lower() in (
    "1",
    "true",
    "yes",
    "on",
)


def current_user() -> dict | None:
    for header in ("X-Auth-User", "X-Forwarded-User"):
        user = (request.headers.get(header) or "").strip()
        if user:
            return {"username": user, "role": "admin", "source": "proxy"}
    return None


def install_auth(app, *, service: str = "admin portal") -> None:
    @app.before_request
    def _enforce_auth():
        if not AUTH_ENABLED:
            return None
        if request.path in ("/healthz",):
            return None
        if current_user():
            return None
        port = os.environ.get("PORT_PORTAL", "8443")
        abort(
            403,
            description=(
                f"Authentication required. Open the {service} via the clawlab portal "
                f"(port {port}) after claw-auth login — not the raw loopback URL."
            ),
        )
