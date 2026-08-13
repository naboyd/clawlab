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
import json
import os
import secrets
import sys
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

_AUTHD_DIR = Path(__file__).resolve().parent
if str(_AUTHD_DIR) not in sys.path:
    sys.path.insert(0, str(_AUTHD_DIR))

try:
    import openclaw_devices
except ImportError:
    openclaw_devices = None  # type: ignore[assignment]

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

_PORTALS = Path(__file__).resolve().parent.parent / "claw-portals"
if _PORTALS.is_dir() and str(_PORTALS) not in sys.path:
    sys.path.insert(0, str(_PORTALS))
try:
    import claw_assets as _claw_assets
except ImportError:
    _claw_assets = None  # type: ignore[assignment]

if _claw_assets:
    _claw_assets.register_routes(app)

BRAND_HEAD = _claw_assets.head_tags() if _claw_assets else ""
BRAND_ICON = "/clawlab-assets/favicon-32.png"


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
{{ brand_head|safe }}
<style>{{ style }}</style></head><body>
<div class="card">
  <h1 style="margin-top:0;display:flex;align-items:center;gap:.5rem">
    <img src="{{ brand_icon }}" alt="" width="32" height="32" style="border-radius:8px">
    clawlab admin login</h1>
  <p class="hint">One login for the clawlab portal hub (OpenClaw, MCP Admin, DefenseClaw).
  First OpenClaw use: open the Control UI, then approve the browser device on the
  <strong>OpenClaw devices</strong> tab (admins).</p>
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
{{ brand_head|safe }}
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
  .pair-banner{background:#3d2e00;border:1px solid #8a6d00;color:#ffe082;
               padding:.55rem 1rem;font-size:.88rem;text-align:center}
  .pair-banner a{color:#8ab4ff}
  .tab .badge{display:inline-block;margin-left:.35rem;padding:.05rem .45rem;
              border-radius:999px;background:#c5221f;color:#fff;font-size:.72rem}
  .hint{color:#9aa0a6;font-size:.85rem;line-height:1.45}
</style></head><body>
{% if is_admin or pending_banner %}
<div class="pair-banner"{% if not pending_banner %} style="display:none"{% endif %}>{{ pending_banner|safe }}</div>
{% endif %}
<header>
  <h1 style="display:flex;align-items:center;gap:.5rem">
    <img src="{{ brand_icon }}" alt="" width="28" height="28" style="border-radius:7px">
    clawlab</h1>
  <div class="meta">Signed in as <b>{{ user.username }}</b>{% if is_admin %}
    <a href="{{ ext_url('/admin/users') }}">Users</a>{% endif %}
    <a href="{{ ext_url('/logout') }}">Sign out</a></div>
</header>
<nav class="tabs">
  {% for tab in tabs %}
  <button type="button" class="tab{% if loop.first %} active{% endif %}"
          data-tab="{{ tab.id }}" onclick="showTab('{{ tab.id }}')">{{ tab.label }}{% if tab.badge %}<span class="badge">{{ tab.badge }}</span>{% endif %}</button>
  {% endfor %}
</nav>
<div class="frame-wrap">
  {% for tab in tabs %}
  {% if tab.external %}
  <div id="panel-{{ tab.id }}" class="hub-panel{% if loop.first %} active{% endif %}">
    <div class="external-card">
      <h2>{{ tab.label }}</h2>
      <p class="hint"><strong>First time in this browser:</strong> click Open below{% if is_admin %}, then approve the
      pending device on the <strong>OpenClaw devices</strong> tab{% else %}, then ask an admin to approve your device
      on the <strong>OpenClaw devices</strong> tab{% endif %}.
      The Control UI cannot connect until pairing is approved.</p>
      <p class="hint">OpenClaw blocks iframe embedding (gateway clickjacking protection).
      The link includes your gateway token{% if mcp_bind %} and MCP identity bind
      (<code>clawBind</code>){% endif %}.
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
<script>
(function(){
  var banner = document.querySelector('.pair-banner');
  if (!banner) return;
  {% if is_admin %}
  function refresh(){
    fetch('{{ ext_url("/admin/openclaw-devices/status") }}', {credentials:'same-origin'})
      .then(function(r){ return r.ok ? r.json() : null; })
      .then(function(d){
        if (!d || !d.pending) return;
        if (d.pending === 0) {
          banner.style.display='none';
          var tabBtn = document.querySelector('[data-tab="openclaw-devices"]');
          if (tabBtn) {
            var badge = tabBtn.querySelector('.badge');
            if (badge) badge.remove();
          }
          return;
        }
        banner.style.display='block';
        banner.innerHTML = d.pending + ' OpenClaw device(s) waiting for approval — '
          + '<a href="#" onclick="showTab(\'openclaw-devices\');return false;">Open OpenClaw devices tab</a>';
      }).catch(function(){});
  }
  setInterval(refresh, 15000);
  {% endif %}
})();
</script>
</body></html>
"""

DEVICES_PAGE = """
<!doctype html><html><head><meta charset="utf-8"><title>OpenClaw devices</title>
<style>{{ style }}
.btn-sm{padding:.35rem .7rem;font-size:.82rem}
.pending{background:#fff8e6}
</style></head><body>
<div class="card">
  <h1 style="margin-top:0">OpenClaw device pairing</h1>
  <p><a href="{{ ext_url('/') }}">&larr; portal hub</a></p>
  <p class="hint">After you open the OpenClaw Control UI in a new browser, a pending pairing
  request appears here. Approve it before the Control UI can connect. If one pending remains
  after approve, it is often a <strong>scope upgrade</strong> or a second tab — refresh and
  approve the latest request id (or close extra Control UI windows).</p>
  {% if msg %}<div class="banner{% if msg_err %} err{% endif %}">{{ msg }}</div>{% endif %}
  {% if error %}<div class="banner err">{{ error }}</div>{% endif %}
  <h2>Pending ({{ pending_rows|length }})</h2>
  {% if pending_rows %}
  <table>
    <tr><th>Request</th><th>Role</th><th>Details</th><th></th></tr>
    {% for row in pending_rows %}
    <tr class="pending">
      <td><code>{{ row.id }}</code></td>
      <td>{{ row.role }}</td>
      <td class="hint">{{ row.detail }}</td>
      <td>
        <form method="post" style="display:inline" onsubmit="return confirm('Approve this device?')">
          <input type="hidden" name="action" value="approve">
          <input type="hidden" name="request_id" value="{{ row.request_id }}">
          <button type="submit" class="btn-sm">Approve</button>
        </form>
      </td>
    </tr>
    {% endfor %}
  </table>
  {% else %}
  <p class="hint">No pending requests. Open the <strong>OpenClaw</strong> tab and click
  <em>Open OpenClaw</em>, then refresh this page.</p>
  {% endif %}
  <h2>Paired ({{ paired_rows|length }})</h2>
  {% if paired_rows|length > 1 %}
  <p class="hint">Multiple paired entries are normal — each browser profile, tab reconnect, or
  scope upgrade can register a separate device. You only need one working Control UI session.</p>
  {% endif %}
  {% if paired_rows %}
  <table>
    <tr><th>Device</th><th>Role</th><th>Details</th></tr>
    {% for row in paired_rows %}
    <tr>
      <td><code>{{ row.id }}</code></td>
      <td>{{ row.role }}</td>
      <td class="hint">{{ row.detail }}</td>
    </tr>
    {% endfor %}
  </table>
  {% else %}
  <p class="hint">No paired devices yet.</p>
  {% endif %}
  <p class="hint" style="margin-top:1.2rem">Source: {{ list_source }}. Gateway: {{ gateway_url }}</p>
  <p><a href="">Refresh</a></p>
</div>
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
    <tr><th>Username</th><th>Role</th><th>Webex email</th><th>Created</th><th></th></tr>
    {% for u in users %}
    <tr>
      <td>{{ u.username }}</td>
      <td>{{ u.role }}</td>
      <td>
        <form method="post" style="display:flex;gap:.35rem;align-items:center">
          <input type="hidden" name="action" value="set_webex_email">
          <input type="hidden" name="username" value="{{ u.username }}">
          <input type="email" name="webex_email" value="{{ u.webex_email or '' }}" placeholder="user@cisco.com" style="min-width:14rem">
          <button type="submit">save</button>
        </form>
      </td>
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
    if openclaw_devices is not None:
        tok = openclaw_devices.read_gateway_token()
        if tok:
            return tok
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


def _portal_scheme() -> str:
    scheme = os.environ.get("SCHEME", "").strip().lower()
    if scheme in ("http", "https"):
        return scheme
    hub = os.environ.get("CLAW_PORTAL_HUB_URL", "").strip()
    if hub.startswith("http://"):
        return "http"
    if hub.startswith("https://"):
        return "https"
    proto = (request.headers.get("X-Forwarded-Proto") or "").lower()
    if proto in ("http", "https"):
        return proto
    return "https"


def _ws_scheme() -> str:
    return "wss" if _portal_scheme() == "https" else "ws"


def _openclaw_hub_url(host_header: str = "", *, mcp_bind: str = "") -> str:
    """OpenClaw URL with explicit gatewayUrl + #token (Control UI WS target).

    gatewayUrl must use the same host:port the browser used to load the portal
    (e.g. 192.168.1.10:8443 vs lab.example.com:8443). A mismatch
    often prevents WSS from reaching the gateway (no Mozilla lines in logs).
    """
    page_path = os.environ.get("CLAW_PORTAL_OPENCLAW_PATH", "/openclaw/").strip()
    if not page_path.startswith("/"):
        page_path = "/" + page_path

    host_header = (host_header or "").strip()
    ws = _ws_scheme()
    if host_header:
        host = host_header.split(",")[0].strip()
        if ":" in host:
            hostname, port = host.rsplit(":", 1)
        else:
            hostname, port = host, ("443" if ws == "wss" else "80")
        gw_url = f"{ws}://{hostname}:{port}/openclaw/"
    else:
        portal_url = os.environ.get("CLAW_PORTAL_OPENCLAW_URL", "").strip()
        if portal_url:
            parsed = urlparse(portal_url)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or (443 if ws == "wss" else 80)
            path = (parsed.path or "/openclaw/").rstrip("/") + "/"
            gw_url = f"{ws}://{host}:{port}{path}"
        else:
            gw_url = f"{ws}://127.0.0.1:8083/openclaw/"

    query = f"gatewayUrl={quote(gw_url, safe='')}"
    if mcp_bind:
        query += f"&clawBind={quote(mcp_bind, safe='')}"
    token = _read_gateway_token()
    url = f"{page_path}?{query}"
    if token:
        url += f"#token={quote(token, safe='')}"
    return url


def _device_snapshot() -> dict:
    if openclaw_devices is None:
        return {"pending": [], "paired": [], "source": "unavailable", "error": "module missing"}
    try:
        return openclaw_devices.list_devices()
    except Exception as exc:  # noqa: BLE001
        log.exception("device_list_failed")
        return {"pending": [], "paired": [], "source": "error", "error": str(exc)}


def _device_display_rows(
    items: list | None,
    *,
    pending: bool = False,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        rid = str(raw.get("requestId") or raw.get("id") or "").strip()
        device_id = str(raw.get("deviceId") or "").strip()
        client_id = str(raw.get("clientId") or raw.get("client") or "").strip()
        display_name = str(raw.get("displayName") or raw.get("operatorLabel") or "").strip()
        if pending:
            if not rid:
                continue
            row_id = rid
        else:
            row_id = device_id or display_name or client_id or rid
            if not row_id:
                continue
        role = str(
            raw.get("role")
            or raw.get("requestedRole")
            or raw.get("approvedRole")
            or ""
        ).strip()
        parts: list[str] = []
        if display_name:
            parts.append(f"name={display_name}")
        if client_id and client_id != display_name:
            parts.append(f"client={client_id}")
        if device_id and device_id != row_id:
            parts.append(f"device={device_id[:12]}")
        scopes = raw.get("scopes") or raw.get("requestedScopes") or raw.get("approvedScopes")
        if scopes:
            parts.append(f"scopes={scopes}")
        if raw.get("isRepair"):
            parts.append("scope upgrade")
        if raw.get("remoteIp"):
            parts.append(f"ip={raw.get('remoteIp')}")
        detail = raw.get("summary") or raw.get("userAgent")
        if not detail and not parts:
            detail = raw.get("publicKey")
        if isinstance(detail, (dict, list)):
            detail = json.dumps(detail, sort_keys=True)
        if parts:
            prefix = ", ".join(str(p) for p in parts)
            detail = prefix if not detail else f"{prefix} — {detail}"
        detail = str(detail or "").strip() or "-"
        if len(detail) > 240:
            detail = detail[:237] + "..."
        rows.append(
            {
                "id": row_id or "?",
                "role": role or "-",
                "detail": detail,
                "request_id": rid if pending else "",
            }
        )
    return rows


def _pending_banner_html(pending_n: int, *, is_admin: bool) -> str:
    if pending_n <= 0:
        return ""
    if is_admin:
        return (
            f"{pending_n} OpenClaw device(s) waiting for approval — "
            'open the <a href="#" onclick="showTab(\'openclaw-devices\');return false;">'
            "OpenClaw devices</a> tab to approve."
        )
    return (
        f"{pending_n} OpenClaw device(s) waiting for admin approval — "
        "open the OpenClaw tab first, then ask an admin to approve on "
        "<strong>OpenClaw devices</strong>."
    )


def _portal_tabs(
    host_header: str = "",
    *,
    mcp_bind: str = "",
    pending_n: int = 0,
    is_admin: bool = False,
) -> list[dict]:
    tabs: list[dict] = [
        {
            "id": "openclaw",
            "label": "OpenClaw",
            "external": _openclaw_hub_url(host_header, mcp_bind=mcp_bind),
        },
    ]
    if is_admin:
        tabs.append(
            {
                "id": "openclaw-devices",
                "label": "OpenClaw devices",
                "admin_only": True,
                "src": "/admin/openclaw-devices",
                "badge": str(pending_n) if pending_n > 0 else "",
            }
        )
    tabs.extend(
        [
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
    )
    return tabs


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
            brand_head=BRAND_HEAD,
            brand_icon=BRAND_ICON,
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
            brand_head=BRAND_HEAD,
            brand_icon=BRAND_ICON,
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


@app.route("/mcp/bind")
def mcp_bind():
    """Issue a short-lived token for verified MCP identity (OpenClaw chat path)."""
    sess = _session_user()
    if not sess:
        return ("", 401)
    try:
        token = store.create_mcp_bind(sess["username"])
    except ValueError as exc:
        return (str(exc), 400)
    return {
        "token": token,
        "username": sess["username"],
        "role": sess["role"],
    }


@app.route("/")
def hub():
    sess = _session_user()
    if not sess:
        return _login_redirect(request.full_path)
    portal_host = request.headers.get("X-Forwarded-Host") or request.host
    mcp_bind = ""
    try:
        mcp_bind = store.create_mcp_bind(sess["username"])
    except ValueError:
        mcp_bind = ""
    is_admin = sess.get("role") == "admin"
    devices = _device_snapshot()
    pending_n = len(_device_display_rows(devices.get("pending"), pending=True))
    return render_template_string(
        HUB_PAGE,
        style=STYLE,
        brand_head=BRAND_HEAD,
        brand_icon=BRAND_ICON,
        user=sess,
        mcp_bind=mcp_bind,
        tabs=_portal_tabs(
            portal_host,
            mcp_bind=mcp_bind,
            pending_n=pending_n,
            is_admin=is_admin,
        ),
        links=_portal_links(),
        pending_banner=_pending_banner_html(pending_n, is_admin=is_admin),
        is_admin=is_admin,
    )


@app.route("/admin/openclaw-devices/status")
def openclaw_devices_status():
    sess = _session_user()
    if not sess:
        return ("", 401)
    if sess["role"] != "admin":
        return ("", 403)
    devices = _device_snapshot()
    pending_n = len(_device_display_rows(devices.get("pending"), pending=True))
    return {
        "pending": pending_n,
        "paired": len(devices.get("paired") or []),
        "source": devices.get("source"),
        "error": devices.get("error"),
    }


@app.route("/admin/openclaw-devices", methods=["GET", "POST"])
def admin_openclaw_devices():
    sess = _session_user()
    if not sess:
        return _login_redirect(request.full_path)
    if sess["role"] != "admin":
        return ("forbidden", 403)

    msg = ""
    msg_err = False
    if request.method == "POST" and request.form.get("action") == "approve":
        rid = (request.form.get("request_id") or "").strip()
        if openclaw_devices is None:
            msg = "openclaw_devices module unavailable."
            msg_err = True
        else:
            result = openclaw_devices.approve_device(rid)
            if result.get("ok"):
                log.info(
                    "device_approve ip=%s admin=%s request_id=%s source=%s",
                    _client_ip(),
                    sess["username"],
                    rid,
                    result.get("source"),
                )
                msg = result.get("warning") or f"Approved device request {rid}."
                if result.get("warning"):
                    msg_err = False
            else:
                msg = result.get("error") or "Approval failed."
                msg_err = True
                log.warning(
                    "device_approve_fail ip=%s admin=%s request_id=%s err=%s",
                    _client_ip(),
                    sess["username"],
                    rid,
                    msg,
                )

    devices = _device_snapshot()
    gw_url = openclaw_devices.gateway_base_url() if openclaw_devices else "-"
    try:
        return render_template_string(
            DEVICES_PAGE,
            style=STYLE,
            user=sess,
            pending_rows=_device_display_rows(devices.get("pending"), pending=True),
            paired_rows=_device_display_rows(devices.get("paired")),
            list_source=devices.get("source") or "none",
            error=devices.get("error") or "",
            gateway_url=gw_url,
            msg=msg,
            msg_err=msg_err,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("openclaw_devices_page_render_failed")
        return (
            f"<h1>OpenClaw devices</h1><p class='err'>Failed to render page: {exc}</p>",
            500,
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
            elif action == "set_webex_email":
                name = (request.form.get("username") or "").strip().lower()
                email = (request.form.get("webex_email") or "").strip()
                store.set_webex_email(name, email)
                msg = f"Updated Webex email for {name}."
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
