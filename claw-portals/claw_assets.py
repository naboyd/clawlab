"""Shared clawlab branding assets (goalie crab icon) for portal Flask apps."""

from __future__ import annotations

import os
from pathlib import Path

from flask import abort, send_from_directory


def assets_dir() -> Path | None:
    env = (os.environ.get("CLAWLAB_REPO") or os.environ.get("CLAWLAB_ASSETS") or "").strip()
    if env:
        p = Path(env)
        if p.name == "assets" and p.is_dir():
            return p
        candidate = p / "docs" / "assets"
        if candidate.is_dir():
            return candidate
    here = Path(__file__).resolve().parent
    candidate = here.parent / "docs" / "assets"
    return candidate if candidate.is_dir() else None


def register_routes(app, *, url_prefix: str = "/clawlab-assets") -> None:
    """Serve docs/assets at /clawlab-assets/ (and /favicon.ico when mounted at portal root)."""
    base = assets_dir()
    if not base:
        return

    prefix = url_prefix.rstrip("/") or "/clawlab-assets"

    @app.route(f"{prefix}/<path:filename>")
    def _clawlab_asset(filename: str):
        safe = Path(filename).name
        if safe != filename or safe.startswith("."):
            abort(404)
        path = base / safe
        if not path.is_file():
            abort(404)
        return send_from_directory(base, safe, max_age=86400)

    @app.route("/favicon.ico")
    def _favicon():
        fav = base / "favicon-32.png"
        if not fav.is_file():
            abort(404)
        return send_from_directory(base, "favicon-32.png", mimetype="image/png", max_age=86400)


def head_tags(*, mount_prefix: str = "") -> str:
    """HTML <head> link tags; mount_prefix is SCRIPT_NAME e.g. /defenseclaw."""
    p = (mount_prefix or "").rstrip("/")
    root = f"{p}/clawlab-assets" if p else "/clawlab-assets"
    return (
        f'<link rel="icon" type="image/png" sizes="32x32" href="{root}/favicon-32.png">\n'
        f'<link rel="apple-touch-icon" sizes="180x180" href="{root}/apple-touch-icon.png">\n'
    )
