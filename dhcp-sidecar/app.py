#!/usr/bin/env python3
"""ISC DHCP sidecar — local Web UI + JSON API for include-file changes."""

from __future__ import annotations

import hmac
import os
import secrets
from functools import wraps
from typing import Any, Callable

from flask import Flask, jsonify, redirect, render_template_string, request, session, url_for

import dhcp_ops

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 512 * 1024
app.secret_key = os.environ.get("DHCP_SIDECAR_SECRET") or os.environ.get("DHCP_SIDECAR_TOKEN") or "dev-insecure-change-me"


def _expected_token() -> str:
    return (os.environ.get("DHCP_SIDECAR_TOKEN") or "").strip()


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template_string(
            LOGIN_HTML,
            error="",
            host=os.environ.get("DHCP_SIDECAR_HOST", "127.0.0.1"),
        )
    expected = _expected_token()
    if not expected:
        return render_template_string(LOGIN_HTML, error="Server misconfigured.", host="127.0.0.1"), 503
    token = (request.form.get("token") or "").strip()
    if not token or not hmac.compare_digest(token, expected):
        return render_template_string(
            LOGIN_HTML,
            error="Invalid or missing token.",
            host=os.environ.get("DHCP_SIDECAR_HOST", "127.0.0.1"),
        ), 401
    session["authenticated"] = True
    return redirect(url_for("index"))


def _token_from_request() -> str:
    auth = (request.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    if session.get("authenticated"):
        return _expected_token()
    return ""


def _auth_required(view: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(view)
    def wrapped(*args: Any, **kwargs: Any):
        expected = _expected_token()
        if not expected:
            return jsonify({"error": "DHCP_SIDECAR_TOKEN not configured", "code": "misconfigured"}), 503
        token = _token_from_request()
        if token and hmac.compare_digest(token, expected):
            return view(*args, **kwargs)
        if request.path.startswith("/api/"):
            return jsonify({"error": "unauthorized", "code": "unauthorized"}), 401
        return redirect(url_for("login"))

    return wrapped


def _error_response(exc: dhcp_ops.DhcpSidecarError, status: int = 400):
    return jsonify({"error": str(exc), "code": exc.code}), status


@app.route("/health")
def health():
    paths = dhcp_ops._paths()
    return jsonify(
        {
            "ok": True,
            "includes_dir": str(paths["includes"]),
            "state_dir": str(paths["state"]),
            "service": dhcp_ops._service_name(),
        }
    )


@app.route("/api/includes", methods=["GET"])
@_auth_required
def api_list_includes():
    return jsonify({"includes": [i.as_dict() for i in dhcp_ops.list_includes()]})


@app.route("/api/includes/<name>", methods=["GET"])
@_auth_required
def api_get_include(name: str):
    try:
        return jsonify(dhcp_ops.read_include(name))
    except dhcp_ops.DhcpSidecarError as exc:
        status = 404 if exc.code == "not_found" else 400
        return _error_response(exc, status)


@app.route("/api/includes/<name>/validate", methods=["POST"])
@_auth_required
def api_validate_include(name: str):
    body = request.get_json(silent=True) or {}
    content = body.get("content")
    if not isinstance(content, str):
        return jsonify({"error": "content required", "code": "invalid_body"}), 400
    try:
        return jsonify(dhcp_ops.validate_include(name, content))
    except dhcp_ops.DhcpSidecarError as exc:
        status = 422 if exc.code == "dhcpd_test_failed" else 400
        payload = {"error": str(exc), "code": exc.code}
        if exc.code == "dhcpd_test_failed":
            payload["dhcpd_test"] = dhcp_ops.run_dhcpd_test(name, content)
        return jsonify(payload), status


@app.route("/api/includes/<name>/apply", methods=["POST"])
@_auth_required
def api_apply_include(name: str):
    body = request.get_json(silent=True) or {}
    content = body.get("content")
    change_id = body.get("change_id")
    if not isinstance(content, str):
        return jsonify({"error": "content required", "code": "invalid_body"}), 400
    if not isinstance(change_id, str) or not change_id.strip():
        return jsonify({"error": "change_id required", "code": "missing_change_id"}), 400
    actor = (request.headers.get("X-Actor") or body.get("actor") or "api").strip()
    try:
        return jsonify(
            dhcp_ops.apply_include(
                name,
                content,
                change_id=change_id.strip(),
                actor=actor[:128],
            )
        )
    except dhcp_ops.DhcpSidecarError as exc:
        status = 422 if exc.code in {
            "dhcpd_test_failed",
            "post_write_test_failed",
            "reload_failed",
        } else 400
        return _error_response(exc, status)


@app.route("/api/rollback/<change_id>", methods=["POST"])
@_auth_required
def api_rollback(change_id: str):
    body = request.get_json(silent=True) or {}
    actor = (request.headers.get("X-Actor") or body.get("actor") or "api").strip()
    try:
        return jsonify(dhcp_ops.rollback_change(change_id, actor=actor[:128]))
    except dhcp_ops.DhcpSidecarError as exc:
        status = 404 if exc.code == "not_found" else 422
        return _error_response(exc, status)


@app.route("/", methods=["GET", "POST"])
@_auth_required
def index():
    includes = [i.as_dict() for i in dhcp_ops.list_includes()]
    selected = (request.args.get("name") or request.form.get("name") or "").strip()
    message = ""
    error = ""
    content = ""
    if selected:
        try:
            content = str(dhcp_ops.read_include(selected).get("content", ""))
        except dhcp_ops.DhcpSidecarError as exc:
            error = str(exc)
            selected = ""

    if request.method == "POST":
        action = request.form.get("action", "")
        selected = (request.form.get("name") or "").strip()
        content = request.form.get("content") or ""
        change_id = (request.form.get("change_id") or "").strip()
        try:
            if action == "validate":
                dhcp_ops.validate_include(selected, content)
                message = f"Validated {selected} — dhcpd -t passed."
            elif action == "apply":
                if not change_id:
                    raise dhcp_ops.DhcpSidecarError("change_id is required", code="missing_change_id")
                result = dhcp_ops.apply_include(
                    selected,
                    content,
                    change_id=change_id,
                    actor="webui",
                )
                message = f"Applied {selected} ({result.get('sha256', '')[:12]}…)."
            else:
                error = f"Unknown action: {action}"
        except dhcp_ops.DhcpSidecarError as exc:
            error = f"{exc.code}: {exc}"

    return render_template_string(
        INDEX_HTML,
        includes=includes,
        selected=selected,
        content=content,
        message=message,
        error=error,
        host=os.environ.get("DHCP_SIDECAR_HOST", "127.0.0.1"),
        port=os.environ.get("DHCP_SIDECAR_PORT", "9080"),
    )


LOGIN_HTML = """<!doctype html>
<title>dhcp-sidecar login</title>
<style>
body{font-family:system-ui,sans-serif;max-width:40rem;margin:2rem auto;padding:0 1rem}
.err{color:#a00}.hint{color:#555;font-size:.9rem}
input[type=password]{width:100%;padding:.5rem}
button{padding:.5rem 1rem;margin-top:.5rem}
</style>
<h1>dhcp-sidecar</h1>
<p class="hint">Local UI on {{ host }}. Paste your sidecar API token.</p>
{% if error %}<p class="err">{{ error }}</p>{% endif %}
<form method="post" action="{{ url_for('login') }}">
  <label>API token<br><input type="password" name="token" autofocus required></label><br>
  <button type="submit">Continue</button>
</form>
"""

INDEX_HTML = """<!doctype html>
<title>dhcp-sidecar</title>
<style>
body{font-family:system-ui,sans-serif;max-width:960px;margin:1.5rem auto;padding:0 1rem}
textarea{width:100%;min-height:14rem;font-family:ui-monospace,monospace}
.ok{color:#060}.err{color:#a00}.hint{color:#555;font-size:.9rem}
table{border-collapse:collapse;width:100%} td,th{border:1px solid #ccc;padding:.35rem .5rem;text-align:left}
code{font-size:.9rem}
.row{display:flex;gap:1rem;flex-wrap:wrap}
.row>*{flex:1 1 14rem}
</style>
<h1>ISC DHCP sidecar</h1>
<p class="hint">Include files in <code>/etc/dhcp/dhcpd.d/</code> · API on {{ host }}:{{ port }} · validate before apply.</p>
{% if message %}<p class="ok">{{ message }}</p>{% endif %}
{% if error %}<p class="err">{{ error }}</p>{% endif %}

<h2>Includes</h2>
<table>
<tr><th>Name</th><th>Bytes</th><th>SHA256</th></tr>
{% for i in includes %}
<tr><td><a href="?name={{ i.name }}">{{ i.name }}</a></td><td>{{ i.bytes }}</td><td><code>{{ i.sha256[:16] }}…</code></td></tr>
{% else %}
<tr><td colspan="3">No include files yet.</td></tr>
{% endfor %}
</table>

<h2>Edit / validate / apply</h2>
<form method="post">
  <div class="row">
    <div><label>Include file name<br>
      <input name="name" value="{{ selected }}" placeholder="vlan100.conf" required pattern="[A-Za-z0-9][A-Za-z0-9._-]*\\.conf"></label></div>
    <div><label>Change ID (apply only)<br>
      <input name="change_id" placeholder="chg-20260814-0042"></label></div>
  </div>
  <p><label>Content<br><textarea name="content">{{ content }}</textarea></label></p>
  <button type="submit" name="action" value="validate">Validate (dhcpd -t)</button>
  <button type="submit" name="action" value="apply">Apply + reload</button>
</form>

<h2>API</h2>
<pre class="hint">GET  /health
GET  /api/includes
POST /api/includes/&lt;name&gt;/validate  {"content":"..."}
POST /api/includes/&lt;name&gt;/apply     {"change_id":"...", "content":"..."}
POST /api/rollback/&lt;change_id&gt;
Authorization: Bearer &lt;DHCP_SIDECAR_TOKEN&gt;</pre>
"""


def main() -> None:
    host = os.environ.get("DHCP_SIDECAR_HOST", "127.0.0.1")
    port = int(os.environ.get("DHCP_SIDECAR_PORT", "9080"))
    if not _expected_token():
        generated = secrets.token_urlsafe(32)
        print("WARN: DHCP_SIDECAR_TOKEN unset — set in /etc/dhcp-sidecar/env", file=os.sys.stderr)
        print(f"DEBUG token (dev only): {generated}", file=os.sys.stderr)
        os.environ["DHCP_SIDECAR_TOKEN"] = generated
    dhcp_ops.ensure_state_dirs()
    print(f"dhcp-sidecar listening on http://{host}:{port}")
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
