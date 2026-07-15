#!/usr/bin/env python3
"""Apply URL prefix when apps are mounted under /ssh-ops/, /defenseclaw/, etc."""

from __future__ import annotations

import os


def apply_mount(app):
    prefix = (os.environ.get("PORTAL_MOUNT_PATH") or "").rstrip("/")
    if not prefix:
        return app

    class _ScriptNameMiddleware:
        def __init__(self, wsgi_app, script_name: str):
            self.wsgi_app = wsgi_app
            self.script_name = script_name

        def __call__(self, environ, start_response):
            environ["SCRIPT_NAME"] = self.script_name
            path = environ.get("PATH_INFO", "") or "/"
            if path.startswith(self.script_name):
                stripped = path[len(self.script_name) :]
                environ["PATH_INFO"] = stripped if stripped.startswith("/") else "/" + stripped
            return self.wsgi_app(environ, start_response)

    try:
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = _ScriptNameMiddleware(
            ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1),
            prefix,
        )
    except ImportError:
        app.wsgi_app = _ScriptNameMiddleware(app.wsgi_app, prefix)

    app.config["APPLICATION_ROOT"] = prefix
    return app
