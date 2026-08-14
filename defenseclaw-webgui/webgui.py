#!/usr/bin/env python3
"""
DefenseClaw policy editor (localhost only)
==========================================

Small Flask app to view and edit DefenseClaw policies: guardrail settings,
rule-pack YAML files, admission actions, webhooks, and firewall rules.

Run:
    pip install -r requirements.txt
    export DEFENSECLAW_CONFIG=~/.defenseclaw/config.yaml   # optional
    python webgui.py            # -> http://127.0.0.1:8770

Secrets in ~/.defenseclaw/.env are never displayed. Expose via nginx+PAM for
LAN access (see nginx/defenseclaw-admin.conf).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import yaml
from flask import Flask, abort, jsonify, redirect, render_template_string, request, url_for

import policy_store as ps

# Optional centralized auth (claw-auth via nginx proxy headers)
_AUTH_DIR = Path(__file__).resolve().parent.parent / "claw-auth"
if _AUTH_DIR.is_dir():
    import sys

    sys.path.insert(0, str(_AUTH_DIR))
try:
    import proxy_middleware as claw_auth
except ImportError:
    claw_auth = None

try:
    import portal_mount
except ImportError:
    portal_mount = None

_PORTALS = Path(__file__).resolve().parent.parent / "claw-portals"
if _PORTALS.is_dir() and str(_PORTALS) not in sys.path:
    sys.path.insert(0, str(_PORTALS))
try:
    import claw_assets as _claw_assets
except ImportError:
    _claw_assets = None  # type: ignore[assignment]

app = Flask(__name__)
if claw_auth:
    claw_auth.install_auth(app, service="DefenseClaw policy editor")
if portal_mount:
    portal_mount.apply_mount(app)
if _claw_assets:
    _claw_assets.register_routes(app)

BRAND_HEAD = _claw_assets.head_tags() if _claw_assets else ""

STYLE = """
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:980px;
     margin:2rem auto;padding:0 1rem;color:#1a1a1a;background:#fafafa}
h1{font-size:1.45rem;margin-bottom:.2rem}
nav{display:flex;flex-wrap:wrap;gap:.35rem;margin:1rem 0 1.4rem}
nav a{padding:.35rem .75rem;border-radius:999px;text-decoration:none;font-size:.85rem;
     background:#fff;border:1px solid #d8d8d8;color:#333}
nav a.active{background:#2c5cff;color:#fff;border-color:#2c5cff}
.card{background:#fff;padding:1.1rem 1.2rem;border:1px solid #e2e2e2;border-radius:8px;
      box-shadow:0 1px 3px #0001;margin-top:1rem}
.banner{background:#eef4ff;border:1px solid #cdddff;padding:.65rem .85rem;border-radius:6px;
        font-size:.88rem;margin:.8rem 0}
.banner.ok{background:#e8f7eb;border-color:#b9e3c0}
.banner.err{background:#fdeeee;border-color:#f0bcbc}
.hint{color:#777;font-size:.82rem}
label{display:block;margin:.55rem 0 .2rem;font-size:.85rem;font-weight:600}
input[type=text],input[type=number],input[type=password],select,textarea{
  width:100%;padding:.45rem;border:1px solid #ccc;border-radius:5px;
  font-size:.9rem;box-sizing:border-box}
textarea{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.82rem}
.row{display:flex;gap:1rem;flex-wrap:wrap}.row>div{flex:1;min-width:220px}
button,.btn{display:inline-block;padding:.5rem 1rem;border:0;border-radius:6px;
             background:#2c5cff;color:#fff;font-size:.88rem;cursor:pointer;text-decoration:none}
button.secondary,.btn.secondary{background:#666}
button.danger{background:#c0392b}
table{border-collapse:collapse;width:100%;background:#fff;margin-top:.6rem}
th,td{border:1px solid #e2e2e2;padding:.45rem .55rem;text-align:left;font-size:.86rem}
th{background:#f0f0f0}
.pill{padding:.1rem .5rem;border-radius:10px;font-size:.75rem}
.yes{background:#d8f5dd;color:#0a5c22}.no{background:#f5e0e0;color:#8a1f1f}
code{background:#eee;padding:.1rem .35rem;border-radius:3px;font-size:.85rem}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:1rem}
@media (max-width:760px){.grid2{grid-template-columns:1fr}}
"""

NAV = """
<nav>
  <a href="{{ url_for('overview') }}" class="{{ 'active' if tab=='overview' else '' }}">Overview</a>
  <a href="{{ url_for('guardrail') }}" class="{{ 'active' if tab=='guardrail' else '' }}">Guardrail</a>
  <a href="{{ url_for('rule_pack') }}" class="{{ 'active' if tab=='rule_pack' else '' }}">Rule pack</a>
  <a href="{{ url_for('actions') }}" class="{{ 'active' if tab=='actions' else '' }}">Actions</a>
  <a href="{{ url_for('webhooks') }}" class="{{ 'active' if tab=='webhooks' else '' }}">Webhooks</a>
  <a href="{{ url_for('firewall') }}" class="{{ 'active' if tab=='firewall' else '' }}">Firewall</a>
  <a href="{{ url_for('ios_xe_policy') }}" class="{{ 'active' if tab=='ios_xe' else '' }}">IOS-XE policy</a>
  <a href="{{ url_for('audit') }}" class="{{ 'active' if tab=='audit' else '' }}">Audit</a>
  <a href="{{ url_for('advanced') }}" class="{{ 'active' if tab=='advanced' else '' }}">Advanced</a>
</nav>
"""

SHELL = """
<!doctype html><html><head><meta charset="utf-8"><title>DefenseClaw policies</title>
{{ brand_head|safe }}
<style>{{ style }}</style></head><body>
<h1 style="display:flex;align-items:center;gap:.45rem">
  <img src="/clawlab-assets/favicon-32.png" alt="" width="26" height="26" style="border-radius:6px">
  DefenseClaw — policy editor</h1>
<p class="hint">Config: <code>{{ config_path }}</code> · Home: <code>{{ home_path }}</code></p>
{% if msg %}<div class="banner {{ msg_class }}">{{ msg }}</div>{% endif %}
{{ nav|safe }}
{% block body %}{% endblock %}
</body></html>
"""


def render_page(template: str, tab: str, **ctx):
    body = render_template_string(template, **ctx)
    shell_ctx = {
        **ctx,
        "style": STYLE,
        "brand_head": BRAND_HEAD,
        "nav": render_template_string(NAV, tab=tab),
        "config_path": str(ps.CONFIG_PATH),
        "home_path": str(ps.DEFENSECLAW_HOME),
        "tab": tab,
    }
    return render_template_string(
        SHELL.replace("{% block body %}{% endblock %}", body),
        **shell_ctx,
    )


def msg_from_query() -> tuple[str, str]:
    text = request.args.get("msg") or ""
    kind = request.args.get("kind") or ("ok" if text else "")
    return text, kind


def _internal_or_admin_authorized() -> bool:
    token = os.environ.get("CLAWLAB_INTERNAL_TOKEN", "").strip()
    if token and request.headers.get("X-Clawlab-Internal-Token") == token:
        return True
    if claw_auth:
        user = claw_auth.current_user()
        if user and (user.get("role") or "").strip().lower() in ("admin", "superadmin"):
            return True
    return False


# --------------------------------------------------------------------------- #
# Overview
# --------------------------------------------------------------------------- #

OVERVIEW = """
<div class="card">
  <h2 style="margin-top:0">Current posture</h2>
  <div class="grid2">
    <div>
      <p><b>Connector</b>: {{ claw_mode }}</p>
      <p><b>Guardrail mode</b>: {{ guardrail_mode }}</p>
      <p><b>Rule pack</b>: <code>{{ rule_pack }}</code></p>
      <p><b>Detection</b>: {{ detection }}</p>
      <p><b>Fail mode</b>: {{ fail_mode }}</p>
    </div>
    <div>
      <p><b>Policy dir</b>: <code>{{ policy_dir }}</code></p>
      <p><b>Named policies</b>: {{ named_policies or '—' }}</p>
      <p><b>Firewall</b>: <code>{{ firewall_path }}</code></p>
      <p><b>Audit DB</b>: {{ audit_status }}</p>
    </div>
  </div>
</div>

<div class="card">
  <h2 style="margin-top:0">Quick actions</h2>
  <form method="post" action="{{ url_for('validate') }}" style="display:inline">
    <button type="submit">Validate config</button>
  </form>
  <form method="post" action="{{ url_for('reload_gateway') }}" style="display:inline;margin-left:.5rem">
    <button type="submit" class="secondary">Reload gateway</button>
  </form>
  <p class="hint">After changing <code>rule_pack_dir</code> or rule-pack YAML files, reload the
  gateway. OPA named policies use <code>defenseclaw policy activate</code> on the Actions tab.</p>
</div>

<div class="card">
  <h2 style="margin-top:0">Policy surfaces</h2>
  <ul>
    <li><b>Guardrail</b> — in-flight prompt/tool scanning and judge settings in <code>config.yaml</code></li>
    <li><b>Rule pack</b> — regex rules, judge prompts, suppressions under <code>rule_pack_dir</code></li>
    <li><b>Actions</b> — per-severity skill/MCP/plugin admission in <code>config.yaml</code></li>
    <li><b>Firewall</b> — host egress policy in <code>firewall.yaml</code></li>
    <li><b>IOS-XE policy</b> — network device config allow_groups in <code>ios-xe-policy.yaml</code></li>
    <li><b>Webhooks</b> — alert destinations (secrets via env vars only)</li>
  </ul>
  <p class="hint">Run the <code>defenseclaw-canary</code> skill after policy changes to verify
  enforcement and Webex alerting.</p>
</div>
"""


@app.route("/")
def overview():
    msg, msg_class = msg_from_query()
    try:
        cfg = ps.load_config()
    except ps.PolicyError as exc:
        return render_page(
            '<div class="card"><p class="banner err">{{ msg }}</p></div>',
            "overview",
            msg=str(exc),
            msg_class="err",
            claw_mode="—",
            guardrail_mode="—",
            rule_pack="—",
            detection="—",
            fail_mode="—",
            policy_dir="—",
            named_policies="",
            firewall_path="—",
            audit_status="—",
        )
    guardrail = cfg.get("guardrail") or {}
    audit_exists = (ps.DEFENSECLAW_HOME / "audit.db").exists()
    return render_page(
        OVERVIEW,
        "overview",
        msg=msg,
        msg_class=msg_class,
        claw_mode=(cfg.get("claw") or {}).get("mode", "—"),
        guardrail_mode=guardrail.get("mode", "—"),
        rule_pack=str(ps.rule_pack_dir(cfg)),
        detection=guardrail.get("detection_strategy", "—"),
        fail_mode=guardrail.get("hook_fail_mode", "—"),
        policy_dir=str(ps.policy_dir(cfg)),
        named_policies=", ".join(ps.list_named_policies(cfg)) or "",
        firewall_path=str(ps.firewall_path(cfg)),
        audit_status="present" if audit_exists else "missing",
    )


# --------------------------------------------------------------------------- #
# Guardrail
# --------------------------------------------------------------------------- #

GUARDRAIL = """
<div class="card">
  <h2 style="margin-top:0">Guardrail settings</h2>
  <form method="post">
    <div class="row">
      <div><label>Mode</label>
        <select name="mode">
          {% for m in modes %}
          <option value="{{ m }}" {% if m==current.mode %}selected{% endif %}>{{ m }}</option>
          {% endfor %}
        </select></div>
      <div><label>Rule pack</label>
        <select name="rule_pack_name">
          {% for p in packs %}
          <option value="{{ p }}" {% if p==current.pack_name %}selected{% endif %}>{{ p }}</option>
          {% endfor %}
          <option value="custom" {% if current.custom %}selected{% endif %}>custom path…</option>
        </select></div>
    </div>
    <label>Custom rule pack path <span class="hint">(when "custom path" selected)</span></label>
    <input type="text" name="rule_pack_custom" value="{{ current.custom_path }}">

    <div class="row">
      <div><label>Detection strategy</label>
        <input type="text" name="detection_strategy" value="{{ current.detection_strategy }}"></div>
      <div><label>Hook fail mode</label>
        <select name="hook_fail_mode">
          {% for f in fail_modes %}
          <option value="{{ f }}" {% if f==current.hook_fail_mode %}selected{% endif %}>{{ f }}</option>
          {% endfor %}
        </select></div>
    </div>

    <h3>LLM judge</h3>
    <div class="row">
      <div><label><input type="checkbox" name="judge_enabled" {% if current.judge_enabled %}checked{% endif %} style="width:auto"> Judge enabled</label></div>
      <div><label><input type="checkbox" name="injection" {% if current.injection %}checked{% endif %} style="width:auto"> Injection</label></div>
      <div><label><input type="checkbox" name="tool_injection" {% if current.tool_injection %}checked{% endif %} style="width:auto"> Tool injection</label></div>
      <div><label><input type="checkbox" name="exfil" {% if current.exfil %}checked{% endif %} style="width:auto"> Exfiltration</label></div>
      <div><label><input type="checkbox" name="pii" {% if current.pii %}checked{% endif %} style="width:auto"> PII</label></div>
    </div>

    <button type="submit">Save guardrail settings</button>
  </form>
</div>
"""


@app.route("/guardrail", methods=["GET", "POST"])
def guardrail():
    cfg = ps.load_config()
    guardrail_cfg = cfg.setdefault("guardrail", {})
    judge = guardrail_cfg.setdefault("judge", {})
    pack_dir = ps.rule_pack_dir(cfg)
    pack_name = pack_dir.name if pack_dir.parent.name == "guardrail" else ""
    custom = pack_name not in ps.BUNDLED_RULE_PACKS

    if request.method == "POST":
        f = request.form
        guardrail_cfg["mode"] = f.get("mode") or guardrail_cfg.get("mode", "action")
        guardrail_cfg["detection_strategy"] = f.get("detection_strategy") or "regex_judge"
        guardrail_cfg["hook_fail_mode"] = f.get("hook_fail_mode") or "closed"
        selected = f.get("rule_pack_name") or "strict"
        if selected == "custom":
            custom_path = (f.get("rule_pack_custom") or "").strip()
            guardrail_cfg["rule_pack_dir"] = custom_path or str(pack_dir)
        else:
            guardrail_cfg["rule_pack_dir"] = str(
                ps.policy_dir(cfg) / "guardrail" / selected
            )
        judge["enabled"] = f.get("judge_enabled") == "on"
        for key in ("injection", "tool_injection", "exfil", "pii"):
            judge[key] = f.get(key) == "on"
        ps.save_config(cfg)
        return redirect(url_for("guardrail", msg="Guardrail settings saved.", kind="ok"))

    current = {
        "mode": guardrail_cfg.get("mode", "action"),
        "pack_name": pack_name or "strict",
        "custom": custom,
        "custom_path": str(pack_dir) if custom else "",
        "detection_strategy": guardrail_cfg.get("detection_strategy", "regex_judge"),
        "hook_fail_mode": guardrail_cfg.get("hook_fail_mode", "closed"),
        "judge_enabled": judge.get("enabled", True),
        "injection": judge.get("injection", True),
        "tool_injection": judge.get("tool_injection", True),
        "exfil": judge.get("exfil", True),
        "pii": judge.get("pii", True),
    }
    return render_page(
        GUARDRAIL,
        "guardrail",
        modes=("action", "monitor", "advisory"),
        packs=ps.BUNDLED_RULE_PACKS,
        fail_modes=("closed", "open"),
        current=current,
    )


# --------------------------------------------------------------------------- #
# Rule pack files
# --------------------------------------------------------------------------- #

RULE_PACK = """
<div class="card">
  <h2 style="margin-top:0">Rule pack files</h2>
  <p class="hint">Editing <code>{{ pack_dir }}</code>. Save then reload the gateway.</p>
  <table>
    <tr><th>File</th><th></th></tr>
    {% for rel in files %}
    <tr>
      <td><code>{{ rel }}</code></td>
      <td><a class="btn" href="{{ url_for('edit_rule_file', relpath=rel) }}">edit</a></td>
    </tr>
    {% else %}
    <tr><td colspan="2" class="hint">No YAML files found. Run <code>defenseclaw init</code> or
    <code>defenseclaw setup guardrail</code> on the host first.</td></tr>
    {% endfor %}
  </table>
</div>
"""

RULE_FILE = """
<div class="card">
  <h2 style="margin-top:0">Edit <code>{{ relpath }}</code></h2>
  <form method="post">
    <label>YAML contents</label>
    <textarea name="content" rows="24">{{ content }}</textarea>
    <button type="submit">Save file</button>
    <a class="btn secondary" href="{{ url_for('rule_pack') }}" style="margin-left:.5rem">Cancel</a>
  </form>
</div>
"""


@app.route("/rule-pack")
def rule_pack():
    pack_dir = ps.rule_pack_dir()
    files = [
        str(p.relative_to(pack_dir.resolve()))
        for p in ps.list_rule_pack_files(pack_dir)
    ]
    return render_page(RULE_PACK, "rule_pack", pack_dir=str(pack_dir), files=files)


@app.route("/rule-pack/edit/<path:relpath>", methods=["GET", "POST"])
def edit_rule_file(relpath: str):
    pack_dir = ps.rule_pack_dir().resolve()
    # Legacy links used paths relative to DEFENSECLAW_HOME; normalize to pack_dir.
    pack_prefix = str(pack_dir.relative_to(ps.DEFENSECLAW_HOME.resolve())).replace("\\", "/")
    if relpath.startswith(pack_prefix + "/"):
        relpath = relpath[len(pack_prefix) + 1 :]
    target = (pack_dir / relpath).resolve()
    if not str(target).startswith(str(pack_dir)):
        return redirect(url_for("rule_pack", msg="Invalid path.", kind="err"))

    if request.method == "POST":
        content = request.form.get("content") or ""
        try:
            yaml.safe_load(content)
        except yaml.YAMLError as exc:
            return render_page(
                RULE_FILE,
                "rule_pack",
                relpath=relpath,
                content=content,
                msg=f"YAML syntax error: {exc}",
                msg_class="err",
            )
        ps.write_text_file(target, content if content.endswith("\n") else content + "\n")
        return redirect(
            url_for("rule_pack", msg=f"Saved {relpath}. Reload the gateway.", kind="ok")
        )

    content = ps.read_text_file(target) if target.exists() else ""
    return render_page(RULE_FILE, "rule_pack", relpath=relpath, content=content)


# --------------------------------------------------------------------------- #
# Actions
# --------------------------------------------------------------------------- #

ACTIONS = """
<div class="card">
  <h2 style="margin-top:0">Admission actions</h2>
  <p class="hint">Per-severity response for skills, MCP servers, and plugins.</p>
  <form method="post">
    {% for kind in kinds %}
    <h3>{{ kind }}</h3>
    <table>
      <tr><th>Severity</th><th>File</th><th>Runtime</th><th>Install</th></tr>
      {% for sev in severities %}
      {% set row = matrix[kind][sev] %}
      <tr>
        <td>{{ sev }}</td>
        {% for field in fields %}
        <td>
          <select name="{{ kind }}__{{ sev }}__{{ field }}">
            {% for val in action_values %}
            <option value="{{ val }}" {% if row[field]==val %}selected{% endif %}>{{ val }}</option>
            {% endfor %}
          </select>
        </td>
        {% endfor %}
      </tr>
      {% endfor %}
    </table>
    {% endfor %}
    <button type="submit">Save actions</button>
  </form>
</div>

<div class="card">
  <h2 style="margin-top:0">OPA named policy</h2>
  <p class="hint">Separate from the guardrail rule pack. Activates a policy YAML under
  <code>{{ policy_dir }}</code>.</p>
  <form method="post" action="{{ url_for('activate_policy') }}">
    <div class="row">
      <div><label>Policy name</label>
        <select name="policy_name">
          {% for name in named_policies %}
          <option value="{{ name }}">{{ name }}</option>
          {% endfor %}
        </select></div>
    </div>
    <button type="submit">Activate policy</button>
  </form>
</div>
"""


@app.route("/actions", methods=["GET", "POST"])
def actions():
    cfg = ps.load_config()
    matrix: dict[str, dict[str, dict[str, str]]] = {}

    if request.method == "POST":
        for kind in ps.ACTION_KINDS:
            section = cfg.setdefault(kind, {})
            for sev in ps.SEVERITIES:
                row = section.setdefault(sev, {})
                for field in ps.ACTION_FIELDS:
                    key = f"{kind}__{sev}__{field}"
                    row[field] = request.form.get(key) or row.get(field, "none")
        ps.save_config(cfg)
        return redirect(url_for("actions", msg="Admission actions saved.", kind="ok"))

    for kind in ps.ACTION_KINDS:
        section = cfg.get(kind) or {}
        matrix[kind] = {}
        for sev in ps.SEVERITIES:
            row = section.get(sev) or {}
            matrix[kind][sev] = {
                field: row.get(field, "none") for field in ps.ACTION_FIELDS
            }

    return render_page(
        ACTIONS,
        "actions",
        kinds=ps.ACTION_KINDS,
        severities=ps.SEVERITIES,
        fields=ps.ACTION_FIELDS,
        action_values=ps.ACTION_VALUES,
        matrix=matrix,
        named_policies=ps.list_named_policies(cfg),
        policy_dir=str(ps.policy_dir(cfg)),
    )


@app.route("/actions/activate", methods=["POST"])
def activate_policy():
    name = (request.form.get("policy_name") or "").strip()
    if not name:
        return redirect(url_for("actions", msg="Policy name required.", kind="err"))
    ok, output = ps.activate_policy(name)
    kind = "ok" if ok else "err"
    return redirect(url_for("actions", msg=output, kind=kind))


# --------------------------------------------------------------------------- #
# Webhooks
# --------------------------------------------------------------------------- #

WEBHOOKS = """
<div class="card">
  <h2 style="margin-top:0">Alert webhooks</h2>
  <p class="hint">Webex uses <code>room_id</code> in the YAML below (target space). Bot bearer token lives in
  <code>~/.defenseclaw/.env</code> as <code>DEFENSECLAW_WEBEX_TOKEN</code> — edit that file to rotate the token;
  this UI never displays secrets. There is no separate “bot ID” field: Webex posts to
  <code>room_id</code> using the bot token.</p>
  <form method="post">
    <label>Webhooks YAML <span class="hint">(list under top-level <code>webhooks:</code>)</span></label>
    <textarea name="webhooks_yaml" rows="18">{{ webhooks_yaml }}</textarea>
    <button type="submit">Save webhooks</button>
    <button type="submit" formaction="{{ url_for('webhooks_test') }}" formmethod="post"
            style="margin-left:.5rem">Send test alert</button>
  </form>
  <p class="hint" style="margin-top:.75rem">Test posts the same synthetic message as
  <code>python3 ~/.defenseclaw/webex-bridge/dc-webex-bridge.py --test</code> to each enabled
  Webex webhook (uses saved config + token from <code>~/.defenseclaw/.env</code>).</p>
  <table style="margin-top:1rem">
    <tr><th>Name</th><th>Type</th><th>Room ID</th><th>Min severity</th><th>Secret env</th><th>Status</th></tr>
    {% for wh in summary %}
    <tr>
      <td>{{ wh.name }}</td>
      <td>{{ wh.type }}</td>
      <td><code>{{ wh.room_id or '—' }}</code></td>
      <td>{{ wh.min_severity }}</td>
      <td><code>{{ wh.secret_env or '—' }}</code></td>
      <td>{% if wh.enabled %}<span class="pill yes">enabled</span>{% else %}<span class="pill no">disabled</span>{% endif %}
          {% if wh.secret_env %} · secret {% if wh.secret_set %}<span class="pill yes">set</span>{% else %}<span class="pill no">missing</span>{% endif %}{% endif %}
      </td>
    </tr>
    {% else %}
    <tr><td colspan="6" class="hint">No webhooks configured.</td></tr>
    {% endfor %}
  </table>
</div>
"""


@app.route("/webhooks", methods=["GET", "POST"])
def webhooks():
    cfg = ps.load_config()
    hooks = cfg.get("webhooks") or []

    if request.method == "POST":
        raw = request.form.get("webhooks_yaml") or ""
        try:
            parsed = yaml.safe_load(raw) or []
        except yaml.YAMLError as exc:
            return render_page(
                WEBHOOKS,
                "webhooks",
                webhooks_yaml=raw,
                summary=[],
                msg=f"YAML syntax error: {exc}",
                msg_class="err",
            )
        if not isinstance(parsed, list):
            return render_page(
                WEBHOOKS,
                "webhooks",
                webhooks_yaml=raw,
                summary=[],
                msg="Webhooks must be a YAML list.",
                msg_class="err",
            )
        cfg["webhooks"] = parsed
        ps.save_config(cfg)
        return redirect(url_for("webhooks", msg="Webhooks saved.", kind="ok"))

    summary = []
    for wh in hooks:
        if not isinstance(wh, dict):
            continue
        secret_env = wh.get("secret_env") or ""
        summary.append(
            {
                "name": wh.get("name", "—"),
                "type": wh.get("type", "—"),
                "room_id": wh.get("room_id") or "",
                "min_severity": wh.get("min_severity", "—"),
                "secret_env": secret_env,
                "secret_set": ps.env_var_set(secret_env),
                "enabled": wh.get("enabled", True),
            }
        )

    webhooks_yaml = yaml.safe_dump(hooks, sort_keys=False, default_flow_style=False)
    msg, msg_class = msg_from_query()
    return render_page(
        WEBHOOKS,
        "webhooks",
        webhooks_yaml=webhooks_yaml,
        summary=summary,
        msg=msg,
        msg_class=msg_class or ("ok" if msg else ""),
    )


@app.route("/webhooks/test", methods=["POST"])
def webhooks_test():
    results = ps.test_webex_webhooks()
    if not results:
        return redirect(
            url_for("webhooks", msg="No webhooks configured.", kind="err")
        )
    parts = []
    all_ok = True
    for item in results:
        if not item["ok"]:
            all_ok = False
        status = "OK" if item["ok"] else "FAIL"
        parts.append(f"{item['name']}: {status} ({item['detail']})")
    msg = "Test alert — " + "; ".join(parts)
    return redirect(url_for("webhooks", msg=msg, kind="ok" if all_ok else "err"))


# --------------------------------------------------------------------------- #
# Firewall
# --------------------------------------------------------------------------- #

FIREWALL = """
<div class="card">
  <h2 style="margin-top:0">Firewall policy</h2>
  <p class="hint">Editing <code>{{ firewall_path }}</code>. DefenseClaw compiles this to
  <code>firewall.pf.conf</code> — do not edit the compiled file by hand.</p>
  <form method="post">
    <textarea name="content" rows="22">{{ content }}</textarea>
    <button type="submit">Save firewall.yaml</button>
  </form>
</div>
"""


@app.route("/firewall", methods=["GET", "POST"])
def firewall():
    fw_path = ps.firewall_path()
    if request.method == "POST":
        content = request.form.get("content") or ""
        try:
            yaml.safe_load(content)
        except yaml.YAMLError as exc:
            return render_page(
                FIREWALL,
                "firewall",
                firewall_path=str(fw_path),
                content=content,
                msg=f"YAML syntax error: {exc}",
                msg_class="err",
            )
        ps.write_text_file(
            fw_path, content if content.endswith("\n") else content + "\n"
        )
        return redirect(
            url_for("firewall", msg="firewall.yaml saved.", kind="ok")
        )

    content = ps.read_text_file(fw_path) if fw_path.exists() else (
        "# DefenseClaw firewall policy\n"
        "default_action: deny\n"
        "destinations: []\n"
    )
    return render_page(
        FIREWALL, "firewall", firewall_path=str(fw_path), content=content
    )


# --------------------------------------------------------------------------- #
# IOS-XE policy (network device config governance)
# --------------------------------------------------------------------------- #

IOS_XE_POLICY = """
<div class="card">
  <h2 style="margin-top:0">IOS-XE configuration policy</h2>
  <p class="hint">Editing <code>{{ policy_path }}</code>. This file defines
  <code>allow_groups</code> (AAA, ACLs, QoS, routing, NetFlow, etc.) and
  <code>always_block</code> patterns used by ssh-ops change approval and merged
  into the DefenseClaw rule pack.</p>
  {% if summary.group_count %}
  <p class="hint"><b>{{ summary.group_count }}</b> allow groups ·
  <b>{{ summary.always_block_count }}</b> always-block rules
  {% if summary.categories %} · categories:
  {% for cat in summary.categories %}{{ cat.label }} ({{ cat.count }}){% if not loop.last %}, {% endif %}{% endfor %}
  {% endif %}
  </p>
  {% endif %}
  {% if mirror_paths %}
  <p class="hint">Save also updates:
  {% for p in mirror_paths %}<code>{{ p }}</code>{% if not loop.last %}, {% endif %}{% endfor %}
  </p>
  {% endif %}
  <form method="post">
    <input type="hidden" name="action" value="save">
    <textarea name="content" rows="28">{{ content }}</textarea>
    <button type="submit">Save ios-xe-policy.yaml</button>
  </form>
  <form method="post" style="margin-top:.75rem">
    <input type="hidden" name="action" value="merge">
    <button type="submit" class="secondary">Merge into DefenseClaw rule pack</button>
  </form>
  <p class="hint">After changing <code>access: deny</code> or <code>always_block</code>,
  click <b>Merge into DefenseClaw rule pack</b> (reloads the DefenseClaw sidecar only).
  Use <b>Reload gateway</b> on Overview if OpenClaw itself needs a restart.
  Per-group access toggles are also on the ssh-ops MCP Admin Policy tab.</p>
</div>
"""


@app.route("/ios-xe-policy", methods=["GET", "POST"])
def ios_xe_policy():
    msg, msg_class = msg_from_query()
    policy_path = ps.ios_xe_policy_path()
    mirror_paths = [str(p) for p in ps.ios_xe_policy_mirror_paths()]

    if request.method == "POST":
        action = (request.form.get("action") or "save").strip().lower()
        if action == "merge":
            ok, output = ps.merge_ios_xe_policy_rules()
            if ok:
                reload_ok, reload_out = ps.reload_defenseclaw_gateway()
                output = f"{output}\n\n{reload_out}"
                if not reload_ok:
                    output += (
                        "\n\n(IOS-XE rules merged; DefenseClaw sidecar reload failed — "
                        "run: defenseclaw-gateway restart)"
                    )
            return redirect(
                url_for(
                    "ios_xe_policy",
                    msg=output,
                    kind="ok" if ok else "err",
                )
            )

        content = request.form.get("content") or ""
        try:
            written = ps.save_ios_xe_policy_content(content)
        except ps.PolicyError as exc:
            summary = {}
            if policy_path.is_file():
                try:
                    summary = ps.ios_xe_policy_summary(
                        yaml.safe_load(policy_path.read_text()) or {}
                    )
                except Exception:  # noqa: BLE001
                    pass
            return render_page(
                IOS_XE_POLICY,
                "ios_xe",
                policy_path=str(policy_path),
                mirror_paths=mirror_paths,
                content=content,
                summary=summary,
                msg=str(exc),
                msg_class="err",
            )
        paths = ", ".join(str(p) for p in written)
        return redirect(
            url_for(
                "ios_xe_policy",
                msg=f"Saved ios-xe-policy.yaml ({paths}). Merge rules if deny/always_block changed.",
                kind="ok",
            )
        )

    if policy_path.is_file():
        content = ps.read_text_file(policy_path)
        try:
            summary = ps.ios_xe_policy_summary(yaml.safe_load(content) or {})
        except Exception:  # noqa: BLE001
            summary = {}
    else:
        content = (
            "# IOS-XE configuration policy\n"
            "version: 1\n"
            "allow_groups: {}\n"
            "always_block: []\n"
        )
        summary = {}
    return render_page(
        IOS_XE_POLICY,
        "ios_xe",
        policy_path=str(policy_path),
        mirror_paths=mirror_paths,
        content=content,
        summary=summary,
        msg=msg,
        msg_class=msg_class,
    )


# --------------------------------------------------------------------------- #
# Audit (read-only)
# --------------------------------------------------------------------------- #

AUDIT = """
<div class="card">
  <h2 style="margin-top:0">Recent audit events</h2>
  <p class="hint">Read-only view of <code>audit.db</code>. Use the Webex bridge for alerting.</p>
  <table>
    <tr><th>ID</th><th>Time</th><th>Action</th><th>Severity</th><th>Target</th><th>Detail</th></tr>
    {% for ev in events %}
    <tr>
      <td>{{ ev.rowid }}</td>
      <td>{{ ev.ts or '—' }}</td>
      <td>{{ ev.action or '—' }}</td>
      <td>{{ ev.severity or '—' }}</td>
      <td>{{ ev.target or '—' }}</td>
      <td class="hint">{{ ev.detail or '—' }}</td>
    </tr>
    {% else %}
    <tr><td colspan="6" class="hint">No events or audit DB unavailable.</td></tr>
    {% endfor %}
  </table>
</div>
"""


@app.route("/audit")
def audit():
    return render_page(AUDIT, "audit", events=ps.recent_audit_events())


# --------------------------------------------------------------------------- #
# Advanced + utilities
# --------------------------------------------------------------------------- #

ADVANCED = """
<div class="card">
  <h2 style="margin-top:0">Full config.yaml</h2>
  <p class="hint">Power users only. Prefer tab-specific editors; this exposes the full
  <code>config.yaml</code>. Keep secrets in <code>.env</code> via <code>*_env</code> keys.</p>
  <form method="post">
    <textarea name="content" rows="28">{{ content }}</textarea>
    <button type="submit">Save config.yaml</button>
  </form>
</div>
"""


@app.route("/advanced", methods=["GET", "POST"])
def advanced():
    if request.method == "POST":
        content = request.form.get("content") or ""
        try:
            parsed = yaml.safe_load(content)
        except yaml.YAMLError as exc:
            return render_page(
                ADVANCED,
                "advanced",
                content=content,
                msg=f"YAML syntax error: {exc}",
                msg_class="err",
            )
        if not isinstance(parsed, dict):
            return render_page(
                ADVANCED,
                "advanced",
                content=content,
                msg="config.yaml must be a YAML mapping.",
                msg_class="err",
            )
        ps.save_config(parsed)
        ok, output = ps.validate_config()
        kind = "ok" if ok else "err"
        return redirect(
            url_for("advanced", msg=f"Saved. Validate: {output}", kind=kind)
        )

    cfg = ps.load_config()
    content = yaml.safe_dump(cfg, sort_keys=False, default_flow_style=False)
    return render_page(ADVANCED, "advanced", content=content)


@app.route("/api/policy/reload-enforcement", methods=["POST"])
def api_policy_reload_enforcement():
    """Internal/admin: merge IOS-XE policy into rule pack and restart sidecars."""
    if not _internal_or_admin_authorized():
        abort(403)

    payload = request.get_json(silent=True) or {}
    reload_openclaw = bool(payload.get("reload_openclaw"))
    if not payload and request.form.get("reload_openclaw") == "1":
        reload_openclaw = True

    ok, merge_out = ps.merge_ios_xe_policy_rules()
    messages = [merge_out]
    if not ok:
        return jsonify({"ok": False, "message": "\n\n".join(messages)}), 500

    sidecar_ok, sidecar_out = ps.reload_defenseclaw_gateway()
    messages.append(sidecar_out)

    openclaw_out = ""
    if reload_openclaw:
        gw_ok, gw_out = ps.reload_gateway()
        openclaw_out = gw_out
        messages.append(gw_out)
        ok = ok and sidecar_ok and gw_ok
    else:
        ok = ok and sidecar_ok

    return jsonify({"ok": ok, "message": "\n\n".join(messages), "reload_openclaw": reload_openclaw})


@app.route("/validate", methods=["POST"])
def validate():
    ok_cfg, out_cfg = ps.validate_config()
    ok_pol, out_pol = ps.policy_validate()
    ok = ok_cfg and ok_pol
    msg = f"config validate:\n{out_cfg}\n\npolicy validate:\n{out_pol}"
    return redirect(url_for("overview", msg=msg, kind="ok" if ok else "err"))


@app.route("/reload-gateway", methods=["POST"])
def reload_gateway():
    ok, output = ps.reload_gateway()
    return redirect(url_for("overview", msg=output, kind="ok" if ok else "err"))


@app.route("/healthz")
def healthz():
    try:
        ps.load_config()
        return {"status": "ok"}, 200
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "detail": str(exc)}, 500


if __name__ == "__main__":
    port = int(os.environ.get("DEFENSECLAW_GUI_PORT", 8770))
    host = os.environ.get("DEFENSECLAW_GUI_HOST", "127.0.0.1")
    app.run(host=host, port=port, debug=False)
