#!/usr/bin/env python3
"""
Shared auth helpers for clawlab Flask admin portals.

When CLAW_AUTH_REQUIRED=1, requests must carry a valid session cookie or arrive
via nginx with X-Auth-User set after auth_request verification.
"""

from __future__ import annotations

import os
from functools import wraps

from flask import abort, redirect, request, session, url_for

import store

SESSION_COOKIE = os.environ.get("CLAW_AUTH_COOKIE", "claw_session")
AUTH_ENABLED = os.environ.get("CLAW_AUTH_REQUIRED", "0").lower() in (
    "1",
    "true",
    "yes",
    "on",
)


def current_user() -> dict | None:
    header_user = (request.headers.get("X-Auth-User") or "").strip()
    if header_user:
        return {"username": header_user, "role": "admin", "source": "proxy"}

    token = request.cookies.get(SESSION_COOKIE)
    sess = store.get_session(token)
    if sess:
        return {
            "username": sess["username"],
            "role": sess["role"],
            "source": "cookie",
        }
    return None


def require_auth(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not AUTH_ENABLED:
            return view(*args, **kwargs)
        user = current_user()
        if user:
            return view(*args, **kwargs)
        if request.path.startswith("/healthz"):
            return view(*args, **kwargs)
        login_url = os.environ.get(
            "CLAW_AUTH_LOGIN_URL", "/_claw_auth/login"
        )
        return redirect(f"{login_url}?next={request.full_path}")

    return wrapped


def require_admin(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            abort(401)
        if user.get("role") != "admin":
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def install_auth(app, login_url: str = "/_claw_auth/login") -> None:
    """Reject unauthenticated requests when CLAW_AUTH_REQUIRED=1.

    Login is handled by nginx + claw-auth; backends only see authenticated
    proxied requests (X-Auth-User / X-Forwarded-User).
    """

    @app.before_request
    def _enforce_auth():
        if not AUTH_ENABLED:
            return None
        if request.path in ("/healthz",):
            return None
        if current_user():
            return None
        abort(403, description="Authentication required. Access via the nginx portal URL.")
