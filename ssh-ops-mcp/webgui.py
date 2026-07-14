#!/usr/bin/env python3
"""
ssh-ops config GUI (localhost only)
===================================

A small Flask app to manage the host inventory (hosts.yaml) and store sudo
passwords ENCRYPTED (via secrets_store -> .env). Binds to 127.0.0.1 only, so it
is not reachable from the network. No login (single-user machine).

Run:
    pip install -r requirements.txt
    export SSH_OPS_CONFIG=/abs/path/hosts.yaml   # same file the MCP server uses
    python webgui.py            # -> http://127.0.0.1:8765

Passwords are never written to hosts.yaml or shown back in the page; only a
"set / not set" indicator is displayed.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from flask import Flask, redirect, render_template_string, request, url_for

import secrets_store

CONFIG_PATH = Path(
    os.environ.get("SSH_OPS_CONFIG", Path(__file__).parent / "hosts.yaml")
).expanduser()

DEFAULT_SETTINGS = {
    "audit_log": "./ssh_ops_audit.log",
    "command_timeout": 30,
    "connect_timeout": 10,
    "host_key_policy": "reject",
}

app = Flask(__name__)


# --------------------------------------------------------------------------- #
# Config helpers
# --------------------------------------------------------------------------- #

def load_config() -> dict:
    if CONFIG_PATH.exists():
        cfg = yaml.safe_load(CONFIG_PATH.read_text()) or {}
    else:
        cfg = {}
    cfg.setdefault("settings", dict(DEFAULT_SETTINGS))
    cfg.setdefault("hosts", {})
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(yaml.safe_dump(cfg, sort_keys=False, default_flow_style=False))
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# Templates
# --------------------------------------------------------------------------- #

PAGE = """
<!doctype html>
<html><head><meta charset="utf-8"><title>ssh-ops config</title>
<style>
  body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:900px;
       margin:2rem auto;padding:0 1rem;color:#1a1a1a;background:#fafafa}
  h1{font-size:1.4rem} h2{font-size:1.1rem;margin-top:2rem}
  table{border-collapse:collapse;width:100%;background:#fff;box-shadow:0 1px 3px #0001}
  th,td{border:1px solid #e2e2e2;padding:.5rem .6rem;text-align:left;font-size:.9rem}
  th{background:#f0f0f0}
  .pill{padding:.1rem .5rem;border-radius:10px;font-size:.75rem}
  .yes{background:#d8f5dd;color:#0a5c22} .no{background:#f5e0e0;color:#8a1f1f}
  form.card{background:#fff;padding:1.2rem;border:1px solid #e2e2e2;border-radius:8px;
            box-shadow:0 1px 3px #0001;margin-top:1rem}
  label{display:block;margin:.6rem 0 .2rem;font-size:.85rem;font-weight:600}
  input[type=text],input[type=password],input[type=number]{width:100%;padding:.45rem;
       border:1px solid #ccc;border-radius:5px;font-size:.9rem;box-sizing:border-box}
  .row{display:flex;gap:1rem}.row>div{flex:1}
  .hint{font-weight:400;color:#777;font-size:.78rem}
  button{margin-top:1rem;padding:.5rem 1.1rem;border:0;border-radius:6px;
         background:#2c5cff;color:#fff;font-size:.9rem;cursor:pointer}
  button.del{background:#c0392b;padding:.25rem .6rem;margin:0;font-size:.78rem}
  .banner{background:#eef4ff;border:1px solid #cdddff;padding:.6rem .8rem;border-radius:6px;
          font-size:.85rem;margin-bottom:1rem}
  code{background:#eee;padding:.1rem .3rem;border-radius:3px}
</style></head><body>
<h1>ssh-ops — host &amp; secret manager</h1>
<div class="banner">Editing <code>{{ config_path }}</code>. Sudo passwords are stored
<b>encrypted</b> in the .env file; the master key is in a separate 0600 keyfile.
This UI is bound to <code>127.0.0.1</code> only.</div>

{% if msg %}<div class="banner">{{ msg }}</div>{% endif %}

<div style="margin:.6rem 0">
  <form method="post" action="{{ url_for('reload_mcp') }}" style="display:inline">
    <button type="submit">Reload hosts into MCP</button>
  </form>
  <span class="hint">New/edited hosts are picked up automatically on the MCP's next call (hot-reload);
  this just forces a refresh now. A full MCP <i>process</i> restart is only needed after a code
  change (rebuild the image + reopen the app) — the web UI can't do that.</span>
</div>

<h2>MCP access</h2>
<div style="margin:.4rem 0">
  <a href="{{ url_for('mcp_token') }}"><button type="button">Manage MCP access token</button></a>
  <span class="hint">Bearer token HTTP MCP clients must send. Rotate or revoke it here.</span>
</div>

<h2>Configured hosts</h2>
<table>
<tr><th>Name</th><th>Platform</th><th>Host</th><th>User</th><th>Port</th>
    <th>Restartable services</th><th>Secrets</th><th></th></tr>
{% for name, h in hosts.items() %}
{% set plat = (h.get('platform','linux') or 'linux')|lower %}
{% set is_net = plat not in ['linux','unix',''] %}
<tr>
  <td><b>{{ name }}</b><br><span class="hint">{{ h.get('description','') }}</span></td>
  <td>{{ plat }}</td>
  <td>{{ h.get('hostname','') }}</td>
  <td>{{ h.get('username','') }}</td>
  <td>{{ h.get('port',22) }}</td>
  <td>{{ ', '.join(h.get('allowed_services',[])) or '—' }}</td>
  <td>
    {% if is_net %}
      login {% if name in with_login %}<span class="pill yes">set</span>{% else %}<span class="pill no">none</span>{% endif %}
      enable {% if name in with_enable %}<span class="pill yes">set</span>{% else %}<span class="pill no">none</span>{% endif %}
    {% else %}
      sudo {% if name in with_secret %}<span class="pill yes">set</span>{% else %}<span class="pill no">none</span>{% endif %}
      {% if name in with_login %}ssh-pw <span class="pill yes">set</span>{% endif %}
    {% endif %}
  </td>
  <td style="white-space:nowrap">
    <a href="{{ url_for('index') }}?edit={{ name }}#form" style="font-size:.8rem;margin-right:.5rem">edit</a>
    <form method="post" action="{{ url_for('delete') }}" style="display:inline"
          onsubmit="return confirm('Delete host {{ name }} and its secret?')">
      <input type="hidden" name="name" value="{{ name }}">
      <button class="del">delete</button>
    </form>
  </td>
</tr>
{% else %}
<tr><td colspan="7" class="hint">No hosts yet — add one below.</td></tr>
{% endfor %}
</table>

<h2 id="form">{% if edit_name %}Edit host: {{ edit_name }}{% else %}Add a host{% endif %}</h2>
{% set eh = edit_host %}
{% set platsel = (eh.get('platform','linux') or 'linux')|lower %}
{% set plabels = {'linux':'linux','cisco_ios':'cisco_ios (IOS / IOS-XE)','cisco_nxos':'cisco_nxos (NX-OS)','cisco_asa':'cisco_asa','arista_eos':'arista_eos','juniper_junos':'juniper_junos'} %}
<form class="card" method="post" action="{{ url_for('save') }}" onsubmit="return validateForm()">
  <div class="row">
    <div><label>Name <span class="hint">(unique id{% if edit_name %}; locked while editing{% endif %})</span></label>
      <input type="text" name="name" required value="{{ edit_name }}" {% if edit_name %}readonly{% endif %}></div>
    <div><label>Platform</label>
      <select name="platform" id="platform" onchange="togglePlatform()"
              style="width:100%;padding:.45rem;border:1px solid #ccc;border-radius:5px">
        {% for p, lbl in plabels.items() %}
        <option value="{{ p }}" {% if platsel==p %}selected{% endif %}>{{ lbl }}</option>
        {% endfor %}
      </select></div>
  </div>
  <div class="row">
    <div><label>Hostname / IP</label><input type="text" name="hostname" required value="{{ eh.get('hostname','') }}"></div>
    <div><label>Port</label><input type="number" name="port" value="{{ eh.get('port',22) }}"></div>
  </div>
  <div class="row">
    <div><label>Username</label><input type="text" name="username" required value="{{ eh.get('username','') }}"></div>
    <div><label>Key path <span class="hint">(optional; blank = ssh-agent / password)</span></label>
      <input type="text" name="key_path" value="{{ eh.get('key_path','') }}" placeholder="/root/.ssh/id_ed25519"></div>
  </div>
  <label>Description</label><input type="text" name="description" value="{{ eh.get('description','') }}">

  <!-- Linux-only fields -->
  <div id="linux-fields">
    <label>SSH login password <span class="hint">(optional; encrypted. Use instead of a key. Blank keeps existing)</span></label>
    <div class="row"><div><input type="password" name="ssh_login_password" autocomplete="new-password" placeholder="password"></div>
      <div><input type="password" name="ssh_login_password_confirm" autocomplete="new-password" placeholder="confirm"></div></div>
    <label>Allowed services <span class="hint">(comma-separated; restart_service is limited to these)</span></label>
    <input type="text" name="allowed_services" value="{{ ', '.join(eh.get('allowed_services',[])) }}" placeholder="nginx, myapp">
    <label>Sudo password <span class="hint">(optional; encrypted, used for sudo -S. Blank keeps existing)</span></label>
    <div class="row"><div><input type="password" name="sudo_password" autocomplete="new-password" placeholder="password"></div>
      <div><input type="password" name="sudo_password_confirm" autocomplete="new-password" placeholder="confirm"></div></div>
    <div class="row" style="margin-top:.6rem">
      <div><label><input type="checkbox" name="use_sudo_for_restart" {% if eh.get('use_sudo_for_restart', True) %}checked{% endif %} style="width:auto"> Use sudo for restarts</label></div>
      <div><label><input type="checkbox" name="use_pty" {% if eh.get('use_pty', False) %}checked{% endif %} style="width:auto"> Request PTY (for <code>requiretty</code> hosts)</label></div>
    </div>
    <div class="row" style="margin-top:.2rem">
      <div><label><input type="checkbox" name="allow_write" {% if eh.get('allow_write', False) %}checked{% endif %} style="width:auto"> <b>Allow write</b> — enable arbitrary commands + file upload on this host <span class="hint">(off = read-only)</span></label></div>
    </div>
  </div>

  <!-- Network-device fields (Cisco IOS-XE etc.) -->
  <div id="net-fields" style="display:none">
    <div class="row">
      <div><label>Login password <span class="hint">(encrypted; blank keeps existing)</span></label>
        <input type="password" name="login_password" autocomplete="new-password" placeholder="password">
        <input type="password" name="login_password_confirm" autocomplete="new-password" placeholder="confirm" style="margin-top:.3rem"></div>
      <div><label>Enable password <span class="hint">(privileged mode; encrypted; blank keeps existing)</span></label>
        <input type="password" name="enable_password" autocomplete="new-password" placeholder="password">
        <input type="password" name="enable_password_confirm" autocomplete="new-password" placeholder="confirm" style="margin-top:.3rem"></div>
    </div>
    <p class="hint">Network devices are read-only: run_command permits show / dir / ping / traceroute only.</p>
  </div>

  <button type="submit">{% if edit_name %}Update host{% else %}Save host{% endif %}</button>
  {% if edit_name %}<a href="{{ url_for('index') }}" style="margin-left:1rem">cancel</a>{% endif %}
</form>
<script>
function togglePlatform(){
  var net = document.getElementById('platform').value !== 'linux';
  document.getElementById('net-fields').style.display = net ? 'block':'none';
  document.getElementById('linux-fields').style.display = net ? 'none':'block';
}
togglePlatform();

function validateForm(){
  var pairs = [
    ['ssh_login_password','ssh_login_password_confirm','SSH login password'],
    ['sudo_password','sudo_password_confirm','sudo password'],
    ['login_password','login_password_confirm','login password'],
    ['enable_password','enable_password_confirm','enable password']
  ];
  for (var i=0;i<pairs.length;i++){
    var a=document.getElementsByName(pairs[i][0])[0];
    var b=document.getElementsByName(pairs[i][1])[0];
    if(!a||!b) continue;
    if(a.value !== b.value){
      alert('The '+pairs[i][2]+' entries do not match. Please re-type them.');
      b.focus();
      return false;
    }
  }
  return true;
}
</script>
</body></html>
"""


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

TOKEN_PAGE = """
<!doctype html>
<html><head><meta charset="utf-8"><title>MCP access token</title>
<style>
 body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:760px;
      margin:2rem auto;padding:0 1rem;color:#1a1a1a;background:#fafafa}
 h1{font-size:1.3rem}
 .banner{background:#eef4ff;border:1px solid #cdddff;padding:.7rem .9rem;border-radius:6px;
         font-size:.9rem;margin:1rem 0}
 .hint{color:#777;font-size:.82rem}
 code{background:#eee;padding:.15rem .4rem;border-radius:4px}
 button{padding:.5rem 1.1rem;border:0;border-radius:6px;background:#2c5cff;color:#fff;
        font-size:.9rem;cursor:pointer;margin-top:.6rem}
 button.del{background:#c0392b}
</style></head><body>
<h1>MCP access token</h1>
<p><a href="{{ url_for('index') }}">&larr; back to hosts</a></p>
{% if note %}<div class="banner">{{ note }}</div>{% endif %}
{% if new_token %}
<div class="banner"><b>New token &mdash; copy it now (won't be shown again):</b><br><br>
<code style="user-select:all;font-size:1rem">{{ new_token }}</code></div>
{% endif %}
<p>Current token: {% if has_current %}<b>set</b>{% else %}<b>none</b>{% endif %}{% if has_prev %}
 &middot; a previous token is still valid (grace window){% endif %}.</p>
<form method="post"><button name="action" value="rotate" type="submit">Rotate token</button></form>
{% if has_prev %}
<form method="post"><button name="action" value="revoke" type="submit" class="del">Revoke previous token</button></form>
{% endif %}
<p class="hint">HTTP MCP clients must send <code>Authorization: Bearer &lt;token&gt;</code>.
After rotating, update your client with the new token; the previous token keeps
working until you click <i>Revoke previous</i>, so you won't lock yourself out.</p>
</body></html>
"""


@app.route("/mcp-token", methods=["GET", "POST"])
def mcp_token():
    new_token = None
    note = None
    if request.method == "POST":
        action = request.form.get("action")
        if action == "rotate":
            new_token = secrets_store.rotate_mcp_token()
            note = "New token generated. Copy it now; the previous token still works until revoked."
        elif action == "revoke":
            secrets_store.clear_mcp_previous()
            note = "Previous token revoked. Only the current token is valid now."
    return render_template_string(
        TOKEN_PAGE,
        new_token=new_token,
        note=note,
        has_current=secrets_store.get_mcp_token() is not None,
        has_prev=secrets_store.has_mcp_previous(),
    )


@app.route("/healthz")
def healthz():
    """Liveness probe for container healthchecks. Verifies config is readable."""
    try:
        load_config()
        return {"status": "ok"}, 200
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "detail": str(exc)}, 500


@app.route("/")
def index():
    cfg = load_config()
    edit_name = (request.args.get("edit") or "").strip()
    edit_host = cfg["hosts"].get(edit_name, {}) if edit_name else {}
    if edit_name and not edit_host:
        edit_name = ""  # unknown host — fall back to add mode
    return render_template_string(
        PAGE,
        hosts=cfg["hosts"],
        with_secret=set(secrets_store.hosts_with_secret("sudo")),
        with_login=set(secrets_store.hosts_with_secret("login")),
        with_enable=set(secrets_store.hosts_with_secret("enable")),
        config_path=str(CONFIG_PATH),
        msg=request.args.get("msg"),
        edit_name=edit_name,
        edit_host=edit_host,
    )


@app.route("/reload", methods=["POST"])
def reload_mcp():
    """Force the MCP's config hot-reload by bumping hosts.yaml's mtime.

    The MCP and GUI are separate processes sharing the config; the MCP re-reads
    it on its next tool call when the mtime changes. (We cannot restart the
    app-spawned MCP process from here — only nudge its hot-reload.)
    """
    try:
        os.utime(os.path.expanduser(str(CONFIG_PATH)), None)
        note = "Config refreshed — the MCP will load host changes on its next call (hot-reload)."
    except OSError as exc:
        note = f"Could not refresh config: {exc}"
    return redirect(url_for("index", msg=note))


@app.route("/save", methods=["POST"])
def save():
    f = request.form
    name = (f.get("name") or "").strip()
    if not name:
        return redirect(url_for("index", msg="Name is required."))

    # Server-side backstop: password must match its confirmation (in case JS is
    # disabled). Nothing is saved on a mismatch.
    for pw_field, label in (("ssh_login_password", "SSH login password"),
                            ("sudo_password", "sudo password"),
                            ("login_password", "login password"),
                            ("enable_password", "enable password")):
        pw = f.get(pw_field) or ""
        if pw and pw != (f.get(pw_field + "_confirm") or ""):
            return redirect(url_for("index", msg=f"{label} entries did not match — nothing saved."))

    cfg = load_config()
    host = cfg["hosts"].get(name, {})

    platform = (f.get("platform") or "linux").strip().lower()
    is_net = platform not in ("linux", "unix", "")

    host["platform"] = platform
    host["description"] = (f.get("description") or "").strip()
    host["hostname"] = (f.get("hostname") or "").strip()
    host["port"] = int(f.get("port") or 22)
    host["username"] = (f.get("username") or "").strip()
    key_path = (f.get("key_path") or "").strip()
    if key_path:
        host["key_path"] = key_path
    else:
        host.pop("key_path", None)

    notes = ["host saved"]
    if is_net:
        # Network device: login + enable secrets; no sudo/services.
        for field in ("allowed_services", "use_sudo_for_restart", "use_pty"):
            host.pop(field, None)
        login_pw = f.get("login_password") or ""
        enable_pw = f.get("enable_password") or ""
        if login_pw:
            secrets_store.set_secret(name, "login", login_pw)
            notes.append("login pw encrypted")
        if enable_pw:
            secrets_store.set_secret(name, "enable", enable_pw)
            notes.append("enable pw encrypted")
    else:
        services = [s.strip() for s in (f.get("allowed_services") or "").split(",") if s.strip()]
        host["allowed_services"] = services
        host["use_sudo_for_restart"] = f.get("use_sudo_for_restart") == "on"
        host["use_pty"] = f.get("use_pty") == "on"
        host["allow_write"] = f.get("allow_write") == "on"
        ssh_login = f.get("ssh_login_password") or ""
        if ssh_login:
            secrets_store.set_secret(name, "login", ssh_login)
            notes.append("ssh login pw encrypted")
        pw = f.get("sudo_password") or ""
        if pw:
            secrets_store.set_sudo_password(name, pw)
            notes.append("sudo pw encrypted")

    cfg["hosts"][name] = host
    save_config(cfg)
    return redirect(url_for("index", msg="; ".join(notes) + "."))


@app.route("/delete", methods=["POST"])
def delete():
    name = (request.form.get("name") or "").strip()
    cfg = load_config()
    if name in cfg["hosts"]:
        del cfg["hosts"][name]
        save_config(cfg)
    secrets_store.delete_all_secrets(name)
    return redirect(url_for("index", msg=f"deleted {name}."))


if __name__ == "__main__":
    port = int(os.environ.get("SSH_OPS_GUI_PORT", 8765))
    # Defaults to loopback. In a container set SSH_OPS_GUI_HOST=0.0.0.0 and
    # publish the port ONLY to the host's loopback, e.g. -p 127.0.0.1:8765:8765,
    # so it still isn't reachable from the network.
    host = os.environ.get("SSH_OPS_GUI_HOST", "127.0.0.1")
    app.run(host=host, port=port, debug=False)
