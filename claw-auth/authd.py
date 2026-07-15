#!/usr/bin/env python3
"""
claw-auth — lightweight centralized auth for clawlab admin portals.

Provides login/logout, nginx auth_request /verify, and a small user admin UI.
Users live in SQLite (~/.claw-auth/users.db); sessions are server-side tokens
in HttpOnly cookies.

Run:
    pip install -r requirements.txt
    python authd.py                 # -> http://127.0.0.1:8780
"""

from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path
from urllib.parse import quote, urlparse

from flask import (
    Flask,
    make_response,
    redirect,
    render_template_string,
    request,
    url_for,
)

import store

SESSION_COOKIE = os.environ.get("CLAW_AUTH_COOKIE", "claw_session")
TOKEN_ENV = "OPENCLAW_GATEWAY_TOKEN"
SECURE_COOKIES = os.environ.get("CLAW_AUTH_SECURE", "auto").lower()
AUTH_PREFIX = os.environ.get("CLAW_AUTH_PREFIX", "").rstrip("/")
LOG_PATH = Path(
    os.environ.get(
        "CLAW_AUTH_LOG",
        Path(os.environ.get("CLAW_AUTH_HOME", Path.home() / ".claw-auth")).expanduser()
        / "auth.log",
    )
).expanduser()
SECRET_KEY_PATH = Path(
    os.environ.get(
        "CLAW_AUTH_SECRET",
        Path.home() / ".claw-auth" / "secret.key",
    )
).expanduser()


def _load_secret_key() -> str:
    SECRET_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    if SECRET_KEY_PATH.exists():
        return SECRET_KEY_PATH.read_text().strip()
    key = secrets.token_hex(32)
    SECRET_KEY_PATH.write_text(key + "\n")
    try:
        os.chmod(SECRET_KEY_PATH, 0o600)
    except OSError:
        pass
    return key


def _cookie_secure() -> bool:
    if SECURE_COOKIES in ("1", "true", "yes", "on"):
        return True
    if SECURE_COOKIES in ("0", "false", "no", "off"):
        return False
    proto = (request.headers.get("X-Forwarded-Proto") or request.scheme or "").lower()
    return proto == "https"


def _safe_next(raw: str | None) -> str:
    if not raw:
        return "/"
    parsed = urlparse(raw)
    if parsed.scheme or parsed.netloc:
        return "/"
    if not raw.startswith("/"):
        return "/"
    return raw


app = Flask(__name__)
app.secret_key = _load_secret_key()


def _setup_logging() -> logging.Logger:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("claw-auth")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    # Always log to stderr -> journalctl --user -u claw-auth
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    logger.addHandler(stream)

    try:
        file_handler = logging.FileHandler(LOG_PATH)
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    except OSError as exc:
        logger.warning("file_log_unavailable path=%s err=%s", LOG_PATH, exc)

    return logger


log = _setup_logging()
log.info(
    "startup log_path=%s auth_prefix=%s port=%s",
    LOG_PATH,
    AUTH_PREFIX or "(direct)",
    os.environ.get("CLAW_AUTH_PORT", "8780"),
)


def _client_ip() -> str:
    forwarded = (request.headers.get("X-Real-IP") or "").strip()
    return forwarded or (request.remote_addr or "unknown")


def _external_path(path: str) -> str:
    """Browser-visible path including nginx mount prefix."""
    if not path.startswith("/"):
        path = "/" + path
    if AUTH_PREFIX and not path.startswith(AUTH_PREFIX + "/") and path != AUTH_PREFIX:
        return AUTH_PREFIX + path
    return path


def _login_redirect(next_path: str | None = None):
    n = _safe_next(next_path or request.full_path or "/")
    return redirect(_external_path(f"/login?next={quote(n, safe='/')}"))


@app.context_processor
def _inject_urls():
    return dict(ext_url=_external_url, auth_prefix=AUTH_PREFIX)


def _external_url(path: str) -> str:
    return _external_path(path)


@app.before_request
def _access_log():
    log.info(
        "request ip=%s method=%s path=%s",
        _client_ip(),
        request.method,
        request.path,
    )

STYLE = """
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:720px;
     margin:2rem auto;padding:0 1rem;color:#1a1a1a;background:#fafafa}
.card{background:#fff;padding:1.2rem;border:1px solid #e2e2e2;border-radius:8px;
      box-shadow:0 1px 3px #0001}
label{display:block;margin:.6rem 0 .2rem;font-weight:600;font-size:.85rem}
input{width:100%;padding:.45rem;border:1px solid #ccc;border-radius:5px;box-sizing:border-box}
button{padding:.5rem 1rem;border:0;border-radius:6px;background:#2c5cff;color:#fff;cursor:pointer}
.banner{background:#eef4ff;border:1px solid #cdddff;padding:.6rem .8rem;border-radius:6px;margin:.8rem 0}
.err{background:#fdeeee;border-color:#f0bcbc}
table{border-collapse:collapse;width:100%;margin-top:1rem}
th,td{border:1px solid #e2e2e2;padding:.45rem .55rem;text-align:left;font-size:.88rem}
th{background:#f0f0f0}
.hint{color:#777;font-size:.82rem}
a{color:#2c5cff}
"""

LOGIN_PAGE = """
<!doctype html><html><head><meta charset="utf-8"><title>clawlab login</title>
<style>{{ style }}</style></head><body>
<div class="card">
  <h1 style="margin-top:0">clawlab admin login</h1>
  <p class="hint">One login for the clawlab portal hub (OpenClaw, MCP Admin, DefenseClaw).</p>
  {% if error %}<div class="banner err">{{ error }}</div>{% endif %}
  <form method="post" action="">
    <input type="hidden" name="next" value="{{ next_url }}">
    <label>Username</label>
    <input type="text" name="username" autocomplete="username" required autofocus>
    <label>Password</label>
    <input type="password" name="password" autocomplete="current-password" required>
    <div style="margin-top:1rem"><button type="submit">Sign in</button></div>
  </form>
</div>
</body></html>
"""

HUB_PAGE = """
<!doctype html><html><head><meta charset="utf-8"><title>clawlab</title>
<style>
  *{box-sizing:border-box}
  body{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
       background:#0f1117;color:#e8eaed;height:100vh;display:flex;flex-direction:column}
  header{display:flex;align-items:center;justify-content:space-between;padding:.65rem 1rem;
          background:#1a1d27;border-bottom:1px solid #2a2f3d}
  header h1{font-size:1.05rem;margin:0;font-weight:600}
  .meta{font-size:.82rem;color:#9aa0a6}
  .meta a{color:#8ab4ff;text-decoration:none;margin-left:.75rem}
  .tabs{display:flex;gap:.35rem;padding:.5rem 1rem;background:#141720;border-bottom:1px solid #2a2f3d}
  .tab{padding:.45rem .95rem;border:1px solid #2a2f3d;border-radius:8px;background:#1f2430;
       color:#c9cdd3;cursor:pointer;font-size:.88rem}
  .tab.active{background:#2c5cff;border-color:#2c5cff;color:#fff}
  .frame-wrap{flex:1;min-height:0;background:#fafafa;display:flex;flex-direction:column}
  iframe{width:100%;height:100%;border:0;display:none;background:#fff;flex:1}
  iframe.active{display:block}
  .hub-panel{display:none;flex:1;align-items:center;justify-content:center;background:#141720;padding:1.5rem}
  .hub-panel.active{display:flex}
  .external-card{max-width:440px;padding:1.5rem 1.75rem;background:#1f2430;border:1px solid #2a2f3d;
                  border-radius:12px;text-align:center}
  .external-card h2{margin:0 0 .6rem;font-size:1.1rem}
  .open-btn{display:inline-block;margin-top:1rem;padding:.65rem 1.25rem;background:#2c5cff;color:#fff;
            border-radius:8px;text-decoration:none;font-size:.9rem}
  .open-btn:hover{background:#3d6dff}
</style></head><body>
<header>
  <h1>clawlab</h1>
  <div class="meta">Signed in as <b>{{ user.username }}</b>
    <a href="{{ ext_url('/admin/users') }}">Users</a>
    <a href="{{ ext_url('/logout') }}">Sign out</a></div>
</header>
<nav class="tabs">
  {% for tab in tabs %}
  <button type="button" class="tab{% if loop.first %} active{% endif %}"
          data-tab="{{ tab.id }}" onclick="showTab('{{ tab.id }}')">{{ tab.label }}</button>
  {% endfor %}
</nav>
<div class="frame-wrap">
  {% for tab in tabs %}
  {% if tab.external %}
  <div id="panel-{{ tab.id }}" class="hub-panel{% if loop.first %} active{% endif %}">
    <div class="external-card">
      <h2>{{ tab.label }}</h2>
      <p class="hint">OpenClaw blocks iframe embedding (gateway clickjacking protection).
      Use the button below — it opens with your gateway token (URL fragment, not sent to nginx logs).
      Do not bookmark plain <code>/openclaw/</code> without the token.</p>
      <a class="open-btn" href="{{ tab.external }}" target="_blank" rel="noopener noreferrer">
        Open {{ tab.label }} ↗</a>
    </div>
  </div>
  {% else %}
  <iframe id="frame-{{ tab.id }}" class="{% if loop.first %}active{% endif %}"
          {% if loop.first %}src="{{ tab.src }}"{% else %}data-src="{{ tab.src }}"{% endif %}
          title="{{ tab.label }}"></iframe>
  {% endif %}
  {% endfor %}
</div>
<script>
function showTab(id){
  document.querySelectorAll('.tab').forEach(function(b){
    b.classList.toggle('active', b.dataset.tab === id);
  });
  document.querySelectorAll('.hub-panel').forEach(function(p){
    p.classList.toggle('active', p.id === 'panel-' + id);
  });
  document.querySelectorAll('iframe').forEach(function(f){
    var on = f.id === 'frame-' + id;
    f.classList.toggle('active', on);
    if (on && f.dataset.src && !f.getAttribute('src')) {
      f.src = f.dataset.src;
    }
  });
}
</script>
</body></html>
"""

ADMIN_PAGE = """
<!doctype html><html><head><meta charset="utf-8"><title>claw-auth users</title>
<style>{{ style }}</style></head><body>
<div class="card">
  <h1 style="margin-top:0">Users</h1>
  <p><a href="{{ ext_url('/') }}">&larr; portal hub</a></p>
  {% if msg %}<div class="banner">{{ msg }}</div>{% endif %}
  <table>
    <tr><th>Username</th><th>Role</th><th>Created</th><th></th></tr>
    {% for u in users %}
    <tr>
      <td>{{ u.username }}</td>
      <td>{{ u.role }}</td>
      <td class="hint">{{ u.created_at }}</td>
      <td>{% if u.username != user.username %}
        <form method="post" style="display:inline" onsubmit="return confirm('Delete {{ u.username }}?')">
          <input type="hidden" name="action" value="delete">
          <input type="hidden" name="username" value="{{ u.username }}">
          <button type="submit">delete</button>
        </form>{% endif %}</td>
    </tr>
    {% endfor %}
  </table>
  <h2>Add user</h2>
  <form method="post">
    <input type="hidden" name="action" value="create">
    <label>Username</label><input type="text" name="username" required>
    <label>Password</label><input type="password" name="password" required>
    <label>Role</label><input type="text" name="role" value="admin">
    <div style="margin-top:1rem"><button type="submit">Create user</button></div>
  </form>
</div>
</body></html>
"""


def _set_session_cookie(resp, token: str):
    resp.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=_cookie_secure(),
        samesite="Lax",
        max_age=store.SESSION_HOURS * 3600,
        path="/",
    )


def _clear_session_cookie(resp):
    resp.set_cookie(
        SESSION_COOKIE,
        "",
        httponly=True,
        secure=_cookie_secure(),
        samesite="Lax",
        max_age=0,
        path="/",
    )


def _read_gateway_token() -> str:
    """Gateway token for Control UI #token= fragment (portal admins only)."""
    val = os.environ.get(TOKEN_ENV, "").strip()
    if val:
        return val
    oc_home = Path(os.environ.get("OPENCLAW_HOME", Path.home() / ".openclaw")).expanduser()
    for fname in (".env", "gateway.systemd.env"):
        path = oc_home / fname
        if not path.is_file():
            continue
        for line in path.read_text().splitlines():
            if line.startswith(f"{TOKEN_ENV}="):
                return line.split("=", 1)[1].strip()
    return ""


def _openclaw_hub_url(host_header: str = "") -> str:
    """OpenClaw URL with explicit gatewayUrl + #token (Control UI WS target).

    gatewayUrl must use the same host:port the browser used to load the portal
    (e.g. 192.168.128.93:8443 vs icecream.naboydciscolab.com:8443). A mismatch
    often prevents WSS from reaching the gateway (no Mozilla lines in logs).
    """
    page_path = os.environ.get("CLAW_PORTAL_OPENCLAW_PATH", "/openclaw/").strip()
    if not page_path.startswith("/"):
        page_path = "/" + page_path

    host_header = (host_header or "").strip()
    if host_header:
        host = host_header.split(",")[0].strip()
        if ":" in host:
            hostname, port = host.rsplit(":", 1)
        else:
            hostname, port = host, "443"
        wss = f"wss://{hostname}:{port}/openclaw/"
    else:
        portal_url = os.environ.get("CLAW_PORTAL_OPENCLAW_URL", "").strip()
        if portal_url:
            parsed = urlparse(portal_url)
            host = parsed.hostname or "icecream.naboydciscolab.com"
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            path = (parsed.path or "/openclaw/").rstrip("/") + "/"
            wss = f"wss://{host}:{port}{path}"
        else:
            wss = "wss://icecream.naboydciscolab.com:8443/openclaw/"

    query = f"gatewayUrl={quote(wss, safe='')}"
    token = _read_gateway_token()
    url = f"{page_path}?{query}"
    if token:
        url += f"#token={quote(token, safe='')}"
    return url


def _portal_tabs(host_header: str = "") -> list[dict]:
    return [
        {
            "id": "openclaw",
            "label": "OpenClaw",
            "external": _openclaw_hub_url(host_header),
        },
        {
            "id": "ssh-ops",
            "label": "MCP Admin",
            "src": os.environ.get("CLAW_PORTAL_SSH_OPS_PATH", "/ssh-ops/"),
        },
        {
            "id": "defenseclaw",
            "label": "DefenseClaw Policies",
            "src": os.environ.get("CLAW_PORTAL_DEFENSECLAW_PATH", "/defenseclaw/"),
        },
    ]


def _portal_links() -> list[dict]:
    links = []
    mapping = (
        ("CLAW_PORTAL_SSH_OPS_URL", "ssh-ops admin", "Host inventory & MCP tokens"),
        ("CLAW_PORTAL_OPENCLAW_URL", "OpenClaw Control UI", "Chat with the governed agent"),
        (
            "CLAW_PORTAL_DEFENSECLAW_URL",
            "DefenseClaw policies",
            "Guardrail & rule-pack editor",
        ),
    )
    for env_key, label, hint in mapping:
        url = os.environ.get(env_key, "").strip()
        if url:
            links.append({"url": url, "label": label, "hint": hint})
    if not links:
        links = [
            {
                "url": os.environ.get("CLAW_PORTAL_DEFAULT_URL", "/"),
                "label": "Return to portal",
                "hint": "Configure CLAW_PORTAL_*_URL in claw-auth.service",
            }
        ]
    return links


def _session_user():
    token = request.cookies.get(SESSION_COOKIE)
    return store.get_session(token)


@app.route("/healthz")
def healthz():
    store.init_db()
    return {"status": "ok", "users": store.user_count()}, 200


@app.route("/login", methods=["GET", "POST"])
def login():
    store.purge_expired_sessions()
    next_url = _safe_next(request.values.get("next"))
    if request.method == "GET":
        existing = _session_user()
        if existing:
            log.info("login_skip ip=%s user=%s next=%s", _client_ip(), existing["username"], next_url)
            return redirect(next_url)
        return render_template_string(
            LOGIN_PAGE,
            style=STYLE,
            error="",
            next_url=next_url,
        )

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    user = store.authenticate(username, password)
    if not user:
        log.warning(
            "login_failed ip=%s user=%s next=%s",
            _client_ip(),
            username.lower() if username else "-",
            next_url,
        )
        return render_template_string(
            LOGIN_PAGE,
            style=STYLE,
            error="Invalid username or password.",
            next_url=next_url,
        ), 401

    token = store.create_session(user["username"])
    log.info("login_ok ip=%s user=%s next=%s", _client_ip(), user["username"], next_url)
    resp = make_response(redirect(next_url))
    _set_session_cookie(resp, token)
    return resp


@app.route("/logout")
def logout():
    token = request.cookies.get(SESSION_COOKIE)
    user = store.get_session(token)
    if token:
        store.delete_session(token)
    if user:
        log.info("logout ip=%s user=%s", _client_ip(), user["username"])
    resp = make_response(redirect(_external_path("/login")))
    _clear_session_cookie(resp)
    return resp


@app.route("/verify")
def verify():
    """nginx auth_request target. 200 + X-Auth-User or 401."""
    store.purge_expired_sessions()
    sess = _session_user()
    if not sess:
        if request.cookies.get(SESSION_COOKIE):
            log.warning("verify_fail ip=%s reason=invalid_or_expired_session", _client_ip())
        return ("", 401)
    resp = make_response("", 200)
    resp.headers["X-Auth-User"] = sess["username"]
    resp.headers["X-Auth-Role"] = sess["role"]
    return resp


@app.route("/")
def hub():
    sess = _session_user()
    if not sess:
        return _login_redirect(request.full_path)
    portal_host = request.headers.get("X-Forwarded-Host") or request.host
    return render_template_string(
        HUB_PAGE,
        style=STYLE,
        user=sess,
        tabs=_portal_tabs(portal_host),
        links=_portal_links(),
    )


@app.route("/admin/users", methods=["GET", "POST"])
def admin_users():
    sess = _session_user()
    if not sess:
        return _login_redirect(request.full_path)
    if sess["role"] != "admin":
        return ("forbidden", 403)

    msg = ""
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "create":
                store.create_user(
                    request.form.get("username") or "",
                    request.form.get("password") or "",
                    (request.form.get("role") or "admin").strip(),
                )
                msg = "User created."
            elif action == "delete":
                name = (request.form.get("username") or "").strip().lower()
                if name == sess["username"]:
                    msg = "Cannot delete yourself."
                else:
                    store.delete_user(name)
                    msg = f"Deleted {name}."
        except ValueError as exc:
            msg = str(exc)

    return render_template_string(
        ADMIN_PAGE,
        style=STYLE,
        user=sess,
        users=store.list_users(),
        msg=msg,
    )


if __name__ == "__main__":
    store.init_db()
    port = int(os.environ.get("CLAW_AUTH_PORT", 8780))
    host = os.environ.get("CLAW_AUTH_HOST", "127.0.0.1")
    app.run(host=host, port=port, debug=False)
