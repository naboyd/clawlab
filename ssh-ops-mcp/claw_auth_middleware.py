#!/usr/bin/env python3
"""Proxy auth gate for ssh-ops webgui in Podman.

When CLAW_AUTH_REQUIRED=1, only requests that nginx authenticated (via claw-auth
auth_request) are allowed — identified by X-Auth-User / X-Forwarded-User headers.
Direct access to :8765 returns 403.
"""

from __future__ import annotations

import os

from flask import abort, request

try:
    from claw_user_lookup import lookup_role
except ImportError:
    lookup_role = None  # type: ignore[assignment]

AUTH_ENABLED = os.environ.get("CLAW_AUTH_REQUIRED", "0").lower() in (
    "1",
    "true",
    "yes",
    "on",
)


def current_user() -> dict | None:
    for header in ("X-Auth-User", "X-Forwarded-User"):
        user = (request.headers.get(header) or "").strip()
        if not user:
            continue
        role_hdr = (request.headers.get("X-Auth-Role") or "").strip().lower()
        role = role_hdr
        if lookup_role is not None:
            db_role = lookup_role(user)
            if db_role:
                role = db_role
        return {
            "username": user,
            "role": role or "operator",
            "source": "proxy",
        }
    return None


def install_auth(app) -> None:
    @app.before_request
    def _enforce_auth():
        if not AUTH_ENABLED:
            return None
        if request.path in ("/healthz",):
            return None
        if request.path.startswith("/webex/hooks/"):
            return None
        if current_user():
            return None
        port = os.environ.get("CLAW_PORTAL_SSH_OPS_PORT", "8443")
        abort(
            403,
            description=(
                "Authentication required. Open the ssh-ops admin portal via nginx "
                f"(port {port}) after claw-auth login — not the raw :8765 URL."
            ),
        )
