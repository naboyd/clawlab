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
import sys
import threading
import time
from pathlib import Path

import yaml
from flask import Flask, jsonify, redirect, render_template_string, request, url_for

import secrets_store
import inventory
import discovery_import
import credential_test

try:
    import change_store
    import change_engine
    import change_actor
    import change_approval
    import ios_xe_policy
    import network_apply
except ImportError:
    change_store = None  # type: ignore[assignment]
    change_engine = None  # type: ignore[assignment]
    change_actor = None  # type: ignore[assignment]
    change_approval = None  # type: ignore[assignment]
    ios_xe_policy = None  # type: ignore[assignment]
    network_apply = None  # type: ignore[assignment]

try:
    import policy_reload
except ImportError:
    policy_reload = None  # type: ignore[assignment]

try:
    import rbac
except ImportError:
    rbac = None  # type: ignore[assignment]

_network_apply_ready = False

try:
    from network_discovery import run_discovery
except ImportError:
    run_discovery = None  # type: ignore[misc, assignment]

try:
    import claw_auth_middleware as claw_auth
except ImportError:
    claw_auth = None

try:
    import portal_mount
except ImportError:
    portal_mount = None

try:
    import webex_approval
except ImportError:
    webex_approval = None  # type: ignore[assignment]

_PORTALS = Path(__file__).resolve().parent.parent / "claw-portals"
if _PORTALS.is_dir() and str(_PORTALS) not in sys.path:
    sys.path.insert(0, str(_PORTALS))
try:
    import claw_assets as _claw_assets
except ImportError:
    _claw_assets = None  # type: ignore[assignment]

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
if claw_auth:
    claw_auth.install_auth(app)
if portal_mount:
    portal_mount.apply_mount(app)
if _claw_assets:
    _claw_assets.register_routes(app)

BRAND_HEAD = _claw_assets.head_tags() if _claw_assets else ""


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

COMMON_STYLE = """
  body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:1050px;
       margin:2rem auto;padding:0 1rem;color:#1a1a1a;background:#fafafa}
  h1{font-size:1.4rem} h2{font-size:1.1rem;margin-top:1.5rem}
  table{border-collapse:collapse;width:100%;background:#fff;box-shadow:0 1px 3px #0001}
  th,td{border:1px solid #e2e2e2;padding:.45rem .55rem;text-align:left;font-size:.85rem;vertical-align:top}
  th{background:#f0f0f0}
  .pill{padding:.1rem .5rem;border-radius:10px;font-size:.75rem}
  .yes{background:#d8f5dd;color:#0a5c22} .no{background:#f5e0e0;color:#8a1f1f}
  form.card{background:#fff;padding:1.2rem;border:1px solid #e2e2e2;border-radius:8px;
            box-shadow:0 1px 3px #0001;margin-top:1rem}
  label{display:block;margin:.5rem 0 .15rem;font-size:.82rem;font-weight:600}
  input[type=text],input[type=password],input[type=number],input[type=file],select{
       width:100%;padding:.4rem;border:1px solid #ccc;border-radius:5px;font-size:.88rem;box-sizing:border-box}
  .row{display:flex;gap:.8rem}.row>div{flex:1}
  .hint{font-weight:400;color:#777;font-size:.78rem}
  button,.btn{display:inline-block;margin-top:.6rem;padding:.45rem 1rem;border:0;border-radius:6px;
         background:#2c5cff;color:#fff;font-size:.88rem;cursor:pointer;text-decoration:none}
  button.del,.btn.del{background:#c0392b;padding:.25rem .6rem;margin:0;font-size:.78rem}
  button.sec,.btn.sec{background:#555}
  .banner{background:#eef4ff;border:1px solid #cdddff;padding:.6rem .8rem;border-radius:6px;
          font-size:.85rem;margin-bottom:1rem}
  .banner.err{background:#fdecea;border-color:#f5c6cb;color:#8a1f1f}
  code{background:#eee;padding:.1rem .3rem;border-radius:3px}
  .tabs{display:flex;gap:0;border-bottom:2px solid #ddd;margin:1.2rem 0 0}
  .tabs a{padding:.55rem 1.1rem;text-decoration:none;color:#555;font-weight:600;font-size:.9rem;
         border-bottom:3px solid transparent;margin-bottom:-2px}
  .tabs a.active{color:#2c5cff;border-bottom-color:#2c5cff}
  .tabs a .badge{background:#2c5cff;color:#fff;border-radius:10px;padding:.05rem .45rem;font-size:.72rem;margin-left:.35rem}
  .tab-panel{display:none}.tab-panel.active{display:block}
  .cell-in{width:100%;min-width:5rem;padding:.3rem;border:1px solid #ddd;border-radius:4px;font-size:.82rem}
  .cell-in.sm{min-width:4rem}
  .skip td{color:#999}
  .actions{white-space:nowrap}
"""

PAGE = """
<!doctype html>
<html><head><meta charset="utf-8"><title>ssh-ops MCP Admin</title>
{{ brand_head|safe }}
<style>{{ common_style|safe }}</style>
<script>
function togglePlatform(){
  var el=document.getElementById('platform');
  if(!el) return;
  var net=el.value!=='linux';
  document.getElementById('net-fields').style.display=net?'block':'none';
  document.getElementById('linux-fields').style.display=net?'none':'block';
}
function toggleMethod(){
  var m=document.getElementById('method');
  if(!m) return;
  document.getElementById('seed-row').style.display=(m.value==='range')?'none':'flex';
  document.getElementById('range-row').style.display=(m.value==='range')?'flex':'none';
}
function toggleAll(cb){
  document.querySelectorAll('input[name=sel]').forEach(function(el){el.checked=cb.checked;});
}
function validateForm(){
  var pairs=[['ssh_login_password','ssh_login_password_confirm','SSH login password'],
    ['sudo_password','sudo_password_confirm','sudo password'],
    ['login_password','login_password_confirm','login password'],
    ['enable_password','enable_password_confirm','enable password']];
  for(var i=0;i<pairs.length;i++){
    var a=document.getElementsByName(pairs[i][0])[0], b=document.getElementsByName(pairs[i][1])[0];
    if(!a||!b) continue;
    if(a.value!==b.value){alert('The '+pairs[i][2]+' entries do not match.'); b.focus(); return false;}
  }
  return true;
}
function setDiscoveryRunning(running){
  var btn=document.getElementById('discovery-run-btn');
  var status=document.getElementById('discovery-status');
  if(btn){btn.disabled=running; btn.textContent=running?'Running discovery…':'Run discovery';}
  if(status && running){status.style.display='block'; status.className='banner'; status.textContent='Discovery in progress — connecting to seed device. This may take several minutes.';}
}
function setChangeApplyRunning(changeId,running){
  var status=document.getElementById('change-apply-status');
  if(changeId){
    var row=document.getElementById('change-'+changeId);
    if(row){
      row.querySelectorAll('.change-apply-btn').forEach(function(btn){
        btn.disabled=running;
        btn.textContent=running?'Applying…':'Apply now';
      });
    }
  }
  if(status){
    if(running){
      status.style.display='block';
      status.className='banner';
      status.textContent='Change '+(changeId||'')+' in progress — backup, push, verify, and write memory. This may take a minute.';
    } else {
      status.style.display='none';
    }
  }
}
function pollDiscoveryStatus(){
  fetch('{{ url_for("discovery_status") }}',{credentials:'same-origin'})
    .then(function(r){return r.json();})
    .then(function(j){
      var status=document.getElementById('discovery-status');
      if(!status) return;
      if(j.status==='running'){
        status.style.display='block';
        status.className='banner';
        status.textContent=j.message||'Discovery running…';
        setDiscoveryRunning(true);
        setTimeout(pollDiscoveryStatus, 2500);
      } else if(j.status==='done'){
        status.style.display='block';
        status.className='banner';
        status.textContent=j.message||'Discovery complete.';
        setDiscoveryRunning(false);
        if(j.reload){ window.location='{{ url_for("index", tab="discovery") }}&msg='+encodeURIComponent(j.message||'Done'); }
      } else if(j.status==='error'){
        status.style.display='block';
        status.className='banner err';
        status.textContent=j.message||'Discovery failed.';
        setDiscoveryRunning(false);
      } else {
        setDiscoveryRunning(false);
      }
    })
    .catch(function(){ setDiscoveryRunning(false); });
}
document.addEventListener('DOMContentLoaded',function(){
  togglePlatform();toggleMethod();
  var form=document.getElementById('discovery-run-form');
  if(form){ form.addEventListener('submit',function(){ setDiscoveryRunning(true); }); }
  document.querySelectorAll('.change-apply-form').forEach(function(f){
    f.addEventListener('submit',function(){
      setChangeApplyRunning(f.getAttribute('data-change-id')||'',true);
    });
  });
  {% if job_status.status == 'running' %}pollDiscoveryStatus();{% endif %}
});
</script></head><body>
<h1 style="display:flex;align-items:center;gap:.45rem">
  <img src="/clawlab-assets/favicon-32.png" alt="" width="26" height="26" style="border-radius:6px">
  ssh-ops — MCP Admin</h1>
<div class="banner">Editing <code>{{ config_path }}</code>. Secrets are stored
<b>encrypted</b> in the .env file; the master key is in a separate 0600 keyfile.
{% if auth_required %}LAN access requires <b>claw-auth</b> via nginx.{% else %}
This UI is bound to <code>127.0.0.1</code> only.{% endif %}</div>
{% if msg %}<div class="banner {% if err %}err{% endif %}">{{ msg }}</div>{% endif %}

<nav class="tabs">
  <a href="{{ url_for('index', tab='hosts') }}" class="{% if tab=='hosts' %}active{% endif %}">Hosts</a>
  <a href="{{ url_for('index', tab='discovery') }}" class="{% if tab=='discovery' %}active{% endif %}">Discovery{% if staging_count %}<span class="badge">{{ staging_count }}</span>{% endif %}</a>
  <a href="{{ url_for('index', tab='changes') }}" class="{% if tab=='changes' %}active{% endif %}">Changes{% if pending_change_count %}<span class="badge">{{ pending_change_count }}</span>{% endif %}</a>
  <a href="{{ url_for('index', tab='policy') }}" class="{% if tab=='policy' %}active{% endif %}">Policy</a>
</nav>

<div id="tab-hosts" class="tab-panel {% if tab=='hosts' %}active{% endif %}">
<div style="margin:.6rem 0">
  <form method="post" action="{{ url_for('reload_mcp') }}" style="display:inline">
    <button type="submit">Reload hosts into MCP</button>
  </form>
  <span class="hint">Forces MCP hot-reload; rebuild the image only after code changes.</span>
</div>
<div style="margin:.4rem 0">
  <a href="{{ url_for('mcp_token') }}" class="btn sec">Manage MCP access token</a>
</div>

{% if network_host_count %}
<h2>Bulk network credentials</h2>
<p class="hint">Apply username and/or login/enable passwords to all {{ network_host_count }} network host(s).
{% if missing_login_count %}{{ missing_login_count }} currently missing a login secret.{% else %}All have login secrets set.{% endif %}</p>
<form class="card" method="post" action="{{ url_for('bulk_network_credentials') }}"
      onsubmit="return confirm('Apply username/credentials to selected network hosts?')">
  <label><input type="checkbox" name="only_missing" value="1" checked style="width:auto">
    Only hosts missing a login secret <span class="hint">(password fields only; username applies to all)</span></label>
  <div class="row">
    <div><label>Username <span class="hint">(optional; updates all network hosts)</span></label>
      <input type="text" name="bulk_username" autocomplete="username" placeholder="e.g. netadmin"></div>
    <div><label>Login password <span class="hint">(optional if only changing username)</span></label>
      <input type="password" name="login_password" autocomplete="new-password" placeholder="password">
      <input type="password" name="login_password_confirm" autocomplete="new-password" placeholder="confirm" style="margin-top:.3rem"></div>
    <div><label>Enable password <span class="hint">(optional; blank = use login password at enable)</span></label>
      <input type="password" name="enable_password" autocomplete="new-password" placeholder="password">
      <input type="password" name="enable_password_confirm" autocomplete="new-password" placeholder="confirm" style="margin-top:.3rem"></div>
  </div>
  <button type="submit">Apply to network hosts</button>
</form>
{% endif %}

{% if hosts %}
<h2>Test credentials</h2>
<p class="hint">Pick a host and test SSH login. Leave passwords blank to use stored secrets, or enter credentials to try before saving.</p>
<form class="card" method="post" action="{{ url_for('test_credentials') }}">
  <div class="row">
    <div><label>Host</label>
      <select name="host" required>
        {% for name, h in hosts.items() %}
        {% set plat = (h.get('platform','linux') or 'linux')|lower %}
        <option value="{{ name }}" {% if test_host_sel == name %}selected{% endif %}>
          {{ name }} — {{ h.get('hostname','') }} ({{ plat }})
        </option>
        {% endfor %}
      </select></div>
    <div><label>Login password <span class="hint">(optional)</span></label>
      <input type="password" name="test_login" autocomplete="new-password" placeholder="blank = stored secret"></div>
    <div><label>Enable password <span class="hint">(network only)</span></label>
      <input type="password" name="test_enable" autocomplete="new-password" placeholder="blank = stored secret"></div>
  </div>
  <button type="submit">Test credentials</button>
</form>
{% endif %}

<h2>Configured hosts</h2>
<table>
<tr><th>Name</th><th>Platform</th><th>Host</th><th>User</th><th>Port</th>
    <th>Services</th><th>Flags</th><th>Secrets</th><th></th></tr>
{% for name, h in hosts.items() %}
{% set plat = (h.get('platform','linux') or 'linux')|lower %}
{% set is_net = plat not in ['linux','unix',''] %}
<tr>
  <td><b>{{ name }}</b><br><span class="hint">{{ ', '.join(inventory.normalize_tags(h)) or '—' }}</span></td>
  <td>{{ plat }}</td>
  <td>{{ h.get('hostname','') }}</td>
  <td>{{ h.get('username','') }}</td>
  <td>{{ h.get('port',22) }}</td>
  <td>{{ ', '.join(h.get('allowed_services',[])) or '—' }}</td>
  <td>
    {% if not is_net %}
      {% if h.get('allow_write') %}<span class="pill yes">write</span>{% else %}<span class="pill no">read-only</span>{% endif %}
      {% if h.get('auto_update') or inventory.has_tag(h, 'auto_update') %}<span class="pill yes">auto-update</span>{% endif %}
    {% else %}—{% endif %}
  </td>
  <td>
    {% if is_net %}
      login {% if name in with_login %}<span class="pill yes">set</span>{% else %}<span class="pill no">none</span>{% endif %}
      enable {% if name in with_enable %}<span class="pill yes">set</span>{% else %}<span class="pill no">none</span>{% endif %}
    {% else %}
      sudo {% if name in with_secret %}<span class="pill yes">set</span>{% else %}<span class="pill no">none</span>{% endif %}
      {% if name in with_login %}ssh-pw <span class="pill yes">set</span>{% endif %}
    {% endif %}
  </td>
  <td class="actions">
    <a href="{{ url_for('index', tab='hosts', edit=name) }}#form" style="font-size:.8rem;margin-right:.5rem">edit</a>
    <form method="post" action="{{ url_for('delete') }}" style="display:inline"
          onsubmit="return confirm('Delete host {{ name }} and its secret?')">
      <input type="hidden" name="name" value="{{ name }}">
      <button class="del">delete</button>
    </form>
  </td>
</tr>
{% else %}
<tr><td colspan="9" class="hint">No hosts yet — add one below or use the Discovery tab.</td></tr>
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
      <select name="platform" id="platform" onchange="togglePlatform()">
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
    <div><label>Key path <span class="hint">(optional)</span></label>
      <input type="text" name="key_path" value="{{ eh.get('key_path','') }}" placeholder="/root/.ssh/id_ed25519"></div>
  </div>
  <label>Tags <span class="hint">(comma-separated)</span></label>
  <input type="text" name="tags" value="{{ ', '.join(edit_tags) }}" placeholder="web, prod">
  <div id="linux-fields">
    <label>SSH login password</label>
    <div class="row"><div><input type="password" name="ssh_login_password" autocomplete="new-password" placeholder="password"></div>
      <div><input type="password" name="ssh_login_password_confirm" autocomplete="new-password" placeholder="confirm"></div></div>
    <label>Allowed services</label>
    <input type="text" name="allowed_services" value="{{ ', '.join(eh.get('allowed_services',[])) }}" placeholder="nginx, myapp">
    <label>Sudo password</label>
    <div class="row"><div><input type="password" name="sudo_password" autocomplete="new-password"></div>
      <div><input type="password" name="sudo_password_confirm" autocomplete="new-password"></div></div>
    <div class="row" style="margin-top:.6rem">
      <div><label><input type="checkbox" name="use_sudo_for_restart" {% if eh.get('use_sudo_for_restart', True) %}checked{% endif %} style="width:auto"> Use sudo for restarts</label></div>
      <div><label><input type="checkbox" name="use_pty" {% if eh.get('use_pty', False) %}checked{% endif %} style="width:auto"> Request PTY</label></div>
    </div>
    <div class="row">
      <div><label><input type="checkbox" name="allow_write" {% if eh.get('allow_write', False) %}checked{% endif %} style="width:auto"> Allow write</label></div>
      <div><label><input type="checkbox" name="auto_update" {% if eh.get('auto_update') or inventory.has_tag(eh, 'auto_update') %}checked{% endif %} style="width:auto"> Auto-update</label></div>
    </div>
  </div>
  <div id="net-fields" style="display:none">
    <div class="row">
      <div><label>Login password</label>
        <input type="password" name="login_password" autocomplete="new-password">
        <input type="password" name="login_password_confirm" autocomplete="new-password" placeholder="confirm" style="margin-top:.3rem"></div>
      <div><label>Enable password</label>
        <input type="password" name="enable_password" autocomplete="new-password">
        <input type="password" name="enable_password_confirm" autocomplete="new-password" placeholder="confirm" style="margin-top:.3rem"></div>
    </div>
  </div>
  <button type="submit">{% if edit_name %}Update host{% else %}Save host{% endif %}</button>
  {% if edit_name %}<a href="{{ url_for('index', tab='hosts') }}" style="margin-left:1rem">cancel</a>{% endif %}
</form>
</div>

<div id="tab-discovery" class="tab-panel {% if tab=='discovery' %}active{% endif %}">
{% if not netmiko_ok %}<div class="banner err">netmiko is not installed — live discovery cannot run (upload YAML still works).</div>{% endif %}

<h2>Run discovery</h2>
<p class="hint">CDP/LLDP hop or CIDR scan via SSH. Results land in the staging list below for review before import.</p>
<div id="discovery-status" class="banner {% if job_status.status == 'error' %}err{% endif %}"
     style="{% if job_status.status in ['running','done','error'] %}display:block{% else %}display:none{% endif %}">
  {{ job_status.message }}
</div>
<form id="discovery-run-form" class="card" method="post" action="{{ url_for('discovery_run') }}">
  <div class="row">
    <div><label>Method</label>
      <select name="method" id="method" onchange="toggleMethod()">
        <option value="cdp" {% if defaults.method=='cdp' %}selected{% endif %}>CDP</option>
        <option value="lldp" {% if defaults.method=='lldp' %}selected{% endif %}>LLDP</option>
        <option value="range" {% if defaults.method=='range' %}selected{% endif %}>IP range (CIDR)</option>
      </select></div>
    <div><label>Max hops</label><input type="number" name="max_hops" value="{{ defaults.max_hops }}" min="1" max="20"></div>
    <div><label>Max workers</label><input type="number" name="max_workers" value="{{ defaults.max_workers }}" min="1" max="50"></div>
  </div>
  <div class="row" id="seed-row">
    <div><label>Seed device IP</label><input type="text" name="seed" id="seed" value="{{ defaults.seed }}" placeholder="10.0.0.1"></div>
  </div>
  <div class="row" id="range-row" style="display:none">
    <div><label>IP range (CIDR)</label><input type="text" name="ip_range" value="{{ defaults.ip_range }}" placeholder="192.168.1.0/24"></div>
  </div>
  <div class="row">
    <div><label>SSH username</label><input type="text" name="username" required value="{{ defaults.username }}"></div>
    <div><label>SSH password</label><input type="password" name="password" required autocomplete="new-password"></div>
    <div><label>Enable password</label><input type="password" name="enable_password" autocomplete="new-password"></div>
  </div>
  <label><input type="checkbox" name="merge" value="1" style="width:auto"> Merge into existing staging (unchecked = replace staging)</label>
  <button id="discovery-run-btn" type="submit" {% if not netmiko_ok or job_status.status == 'running' %}disabled{% endif %}>Run discovery</button>
</form>

<h2>Upload discovery YAML</h2>
<form class="card" method="post" action="{{ url_for('discovery_upload') }}" enctype="multipart/form-data">
  <label>YAML file <span class="hint">(<code>discovered_devices:</code> list)</span></label>
  <input type="file" name="yaml_file" accept=".yaml,.yml,.txt" required>
  <label><input type="checkbox" name="merge" value="1" style="width:auto"> Merge into existing staging</label>
  <button type="submit" class="sec">Upload</button>
</form>

<h2>Staged devices {% if devices %}({{ devices|length }}){% endif %}</h2>
<p class="hint">Edit, add, or remove devices here before importing into the host list. Access points and ISE appliances are marked but can be kept or removed.</p>

{% if devices %}
<form class="card" method="post" action="{{ url_for('discovery_staging_save') }}">
  <table>
  <tr><th>#</th><th>Host key</th><th>Hostname</th><th>IP</th><th>Model</th><th>IOS type</th><th>Tags</th><th></th></tr>
  {% for d in devices %}
  {% set i = loop.index0 %}
  {% set importable = discovery_import.is_importable(d) %}
  <tr class="{% if not importable %}skip{% endif %}">
    <td>{{ i + 1 }}</td>
    <td><input class="cell-in sm" type="text" name="host_key_{{ i }}" value="{{ d.get('host_key','') }}" placeholder="auto"></td>
    <td><input class="cell-in" type="text" name="hostname_{{ i }}" value="{{ d.get('hostname','') }}"></td>
    <td><input class="cell-in sm" type="text" name="ip_{{ i }}" value="{{ d.get('ip','') }}" required></td>
    <td><input class="cell-in sm" type="text" name="model_{{ i }}" value="{{ d.get('model','') }}"></td>
    <td><select class="cell-in sm" name="ios_type_{{ i }}">
      {% for t in ['ios-xe','ios','unknown','access-point','ise-appliance'] %}
      <option value="{{ t }}" {% if (d.get('ios_type') or 'unknown')==t %}selected{% endif %}>{{ t }}</option>
      {% endfor %}
    </select></td>
    <td><input class="cell-in" type="text" name="tags_{{ i }}" value="{{ tags_for_display(d) }}" placeholder="comma-separated"></td>
    <td class="actions">
      <button type="submit" formaction="{{ url_for('discovery_staging_remove', idx=i) }}" formmethod="post" class="del"
              onclick="return confirm('Remove device {{ i + 1 }} from staging?')">remove</button>
    </td>
  </tr>
  {% endfor %}
  </table>
  <input type="hidden" name="device_count" value="{{ devices|length }}">
  <button type="submit">Save staging changes</button>
  <button type="submit" formaction="{{ url_for('discovery_clear') }}" formmethod="post" class="del"
          onclick="return confirm('Clear all staged devices?')">Clear all</button>
</form>
{% else %}
<p class="hint">No staged devices — run discovery or upload YAML above.</p>
{% endif %}

<h2>Add device manually</h2>
<form class="card" method="post" action="{{ url_for('discovery_staging_add') }}">
  <div class="row">
    <div><label>Host key <span class="hint">(optional inventory name)</span></label>
      <input type="text" name="host_key" placeholder="sw-core-01"></div>
    <div><label>Hostname</label><input type="text" name="hostname" placeholder="sw-core-01.example.com"></div>
    <div><label>IP <span class="hint">(required)</span></label><input type="text" name="ip" required placeholder="10.0.0.1"></div>
  </div>
  <div class="row">
    <div><label>Model</label><input type="text" name="model" placeholder="C9300-24T"></div>
    <div><label>IOS type</label>
      <select name="ios_type">
        <option value="ios-xe">ios-xe</option>
        <option value="ios">ios</option>
        <option value="unknown" selected>unknown</option>
        <option value="access-point">access-point</option>
        <option value="ise-appliance">ise-appliance</option>
      </select></div>
    <div><label>Tags</label><input type="text" name="tags" placeholder="discovered, network, core"></div>
  </div>
  <button type="submit">Add to staging</button>
</form>

{% if devices %}
<h2>Import into host list</h2>
<p class="hint">Select devices from staging to add to <code>{{ config_path }}</code>.</p>
<form class="card" method="post" action="{{ url_for('discovery_import') }}">
  <table>
  <tr><th><input type="checkbox" onclick="toggleAll(this)"></th><th>Host key</th><th>Hostname</th><th>IP</th><th>Model</th><th>IOS</th><th>Import?</th></tr>
  {% for d in devices %}
  {% set importable = discovery_import.is_importable(d) %}
  <tr class="{% if not importable %}skip{% endif %}">
    <td>{% if importable %}<input type="checkbox" name="sel" value="{{ loop.index0 }}">{% else %}—{% endif %}</td>
    <td>{{ d.get('host_key') or discovery_import.sanitize_host_key(d.get('hostname',''), d.get('ip','')) }}</td>
    <td>{{ d.get('hostname','?') }}</td>
    <td>{{ d.get('ip','') }}</td>
    <td>{{ d.get('model','') }}</td>
    <td>{{ d.get('ios_type','') }}</td>
    <td>{% if importable %}<span class="pill yes">yes</span>{% else %}<span class="pill no">skip</span>{% endif %}</td>
  </tr>
  {% endfor %}
  </table>
  <div class="row" style="margin-top:1rem">
    <div><label>Import username</label><input type="text" name="import_username" required value="{{ defaults.username }}"></div>
    <div><label>Login password</label><input type="password" name="import_login" required autocomplete="new-password"></div>
    <div><label>Enable password</label><input type="password" name="import_enable" autocomplete="new-password"></div>
  </div>
  <button type="submit">Import selected into hosts</button>
</form>
{% endif %}
</div>

<div id="tab-changes" class="tab-panel {% if tab=='changes' %}active{% endif %}">
<h2>Pending network changes</h2>
<p class="hint">Agents may <code>propose_change</code> only. A <b>different</b> claw-auth user
must approve (four-eyes). <code>apply_change</code> runs after approval.</p>
<div id="change-apply-status" class="banner" style="display:none"></div>
{% if not changes_enabled %}
<div class="banner err">Change modules not available in this container image.</div>
{% else %}
<table>
<tr><th>ID</th><th>Status</th><th>Risk</th><th>Host</th><th>Proposed by</th><th>Intent</th><th>Created</th><th>Actions</th></tr>
{% for c in changes %}
<tr id="change-{{ c.id }}"{% if highlight_change == c.id %} style="background:#eef4ff"{% endif %}>
  <td><code>{{ c.id }}</code></td>
  <td>{{ c.status }}{% if c.status == 'applying' %}<br><span class="hint">in progress…</span>{% endif %}{% if c.failure_stage %}<br><span class="hint">failed at: {{ c.failure_stage }}</span>{% endif %}</td>
  <td>{{ c.risk }}</td>
  <td>{% if c.targets %}{{ c.targets[0].name }}{% else %}—{% endif %}</td>
  <td>{{ c.created_by or '—' }}{% if c.approved_by %}<br><span class="hint">approved: {{ c.approved_by }}</span>{% endif %}</td>
  <td>{{ c.intent or c.change_type }}</td>
  <td>{{ c.created_at or '—' }}</td>
  <td class="actions">
  {% if c.status == 'proposed' %}
  {% if c.can_approve %}
  <form method="post" action="{{ url_for('change_approve') }}" style="display:inline">
    <input type="hidden" name="change_id" value="{{ c.id }}">
    <input type="hidden" name="tab" value="changes">
    <button type="submit">Approve</button>
  </form>
  {% else %}
  <span class="hint" title="Four-eyes: proposer cannot approve">needs other approver</span>
  {% endif %}
  <form method="post" action="{{ url_for('change_reject') }}" style="display:inline">
    <input type="hidden" name="change_id" value="{{ c.id }}">
    <input type="hidden" name="tab" value="changes">
    <button type="submit" class="del">Reject</button>
  </form>
  {% elif c.status == 'approved' %}
  <form method="post" action="{{ url_for('change_apply') }}" class="change-apply-form" data-change-id="{{ c.id }}" style="display:inline">
    <input type="hidden" name="change_id" value="{{ c.id }}">
    <input type="hidden" name="tab" value="changes">
    <button type="submit" class="change-apply-btn">Apply now</button>
  </form>
  {% elif c.status == 'applied' %}
  <form method="post" action="{{ url_for('change_rollback') }}" style="display:inline"
        onsubmit="return confirm('Roll back {{ c.id }}?');">
    <input type="hidden" name="change_id" value="{{ c.id }}">
    <input type="hidden" name="tab" value="changes">
    <button type="submit" class="sec">Rollback</button>
  </form>
  {% else %}—{% endif %}
  </td>
</tr>
{% if c.targets %}
<tr><td colspan="8" style="background:#fafafa">
  <b>Apply:</b> <code>{{ c.targets[0].apply|join('; ') }}</code><br>
  <b>Rollback:</b> <code>{{ c.targets[0].rollback|join('; ') }}</code>
</td></tr>
{% endif %}
{% else %}
<tr><td colspan="8" class="hint">No changes yet.</td></tr>
{% endfor %}
</table>

<h2>Propose IOS local user</h2>
<form method="post" action="{{ url_for('change_propose') }}" class="card">
  <input type="hidden" name="tab" value="changes">
  <div class="row">
    <div><label>Host</label>
      <select name="host" required>
        <option value="">— select —</option>
        {% for n in network_host_names %}
        <option value="{{ n }}">{{ n }}</option>
        {% endfor %}
      </select>
    </div>
    <div><label>Username</label><input type="text" name="username" required maxlength="32"></div>
    <div><label>Privilege</label><input type="number" name="privilege" value="15" min="1" max="15"></div>
  </div>
  <div class="row">
    <div><label>Password / secret</label><input type="password" name="password" required autocomplete="new-password"></div>
    <div><label>Confirm password</label><input type="password" name="password_confirm" required autocomplete="new-password"></div>
    <div><label>Action</label>
      <select name="action"><option value="create">create</option><option value="delete">delete</option></select>
    </div>
  </div>
  <label>Intent (optional)</label><input type="text" name="intent" placeholder="e.g. Add break-glass local account">
  <button type="submit">Propose change</button>
</form>

<h2>Propose IOS config lines</h2>
<p class="hint">Lines must match an <code>allow_groups</code> entry and must not hit
<code>always_block</code>. For a new VLAN <b>and</b> SVI IP on an L3 switch (e.g. C9300),
use group <code>vlan_l3</code> — not <code>vlan</code> or <code>vlan_svi</code> alone.</p>
<form method="post" action="{{ url_for('change_propose_lines') }}" class="card">
  <input type="hidden" name="tab" value="changes">
  <div class="row">
    <div><label>Host</label>
      <select name="host" required>
        <option value="">— select —</option>
        {% for n in network_host_names %}
        <option value="{{ n }}">{{ n }}</option>
        {% endfor %}
      </select>
    </div>
    <div><label>Allow group</label>
      <select name="group" required>
        {% set ns = namespace(cat='') %}
        {% for g in policy_groups %}
        {% if g.category != ns.cat %}
        {% if ns.cat %}</optgroup>{% endif %}
        <optgroup label="{{ g.category_label }}">
        {% set ns.cat = g.category %}
        {% endif %}
        <option value="{{ g.name }}" {% if g.access=='deny' %}disabled{% endif %}
                {% if g.name=='vlan_l3' %}selected{% endif %}>
          {{ g.name }}{% if g.access=='deny' %} (denied){% elif g.access=='allow' %} (auto-approve){% endif %}
        </option>
        {% endfor %}
        {% if ns.cat %}</optgroup>{% endif %}
      </select>
    </div>
  </div>
  <label>Config lines (one per line)</label>
  <textarea name="lines" rows="7" style="width:100%;font-family:monospace;font-size:.85rem" required placeholder="vlan 51&#10; name MGMT&#10;interface Vlan51&#10; ip address 192.168.51.4 255.255.255.0&#10; no shutdown"></textarea>
  <label>Intent (optional)</label><input type="text" name="intent" placeholder="e.g. VLAN 51 SVI on core switch">
  <button type="submit">Propose config lines</button>
</form>
{% endif %}
</div>

<div id="tab-policy" class="tab-panel {% if tab=='policy' %}active{% endif %}">
<h2>IOS-XE config groups</h2>
<p class="hint">Per-group enforcement for config-line proposals (<code>ios_config_lines</code>).
<b>Always deny</b> blocks proposals and adds DefenseClaw CRITICAL rules for the group's patterns.
<b>Approval required</b> is the normal four-eyes flow.
<b>Always allow</b> auto-approves on propose; you still run Apply.</p>
{% if not policy_admin %}
<div class="banner err">Policy changes require <b>admin</b> role.
Signed in as <code>{{ gui_user }}</code> ({{ gui_role }}). Contact an admin to edit group access or reload enforcement.</div>
{% endif %}
{% if not policy_groups %}
<div class="banner err">Policy module not available.</div>
{% else %}
<form method="post" action="{{ url_for('policy_save_groups') }}" class="card">
  <input type="hidden" name="tab" value="policy">
  <table>
  <tr><th>Category</th><th>Group</th><th>Description</th><th>Patterns</th><th>Access</th></tr>
  {% for g in policy_groups %}
  <tr>
    <td class="hint">{{ g.category_label }}</td>
    <td><code>{{ g.name }}</code></td>
    <td>{{ g.description or '—' }}</td>
    <td>{{ g.pattern_count }}</td>
    <td>
      {% if policy_admin %}
      <select name="access_{{ g.name }}">
        <option value="deny" {% if g.access=='deny' %}selected{% endif %}>Always deny</option>
        <option value="approve" {% if g.access=='approve' %}selected{% endif %}>Approval required</option>
        <option value="allow" {% if g.access=='allow' %}selected{% endif %}>Always allow</option>
      </select>
      {% else %}
      {% if g.access=='deny' %}Always deny{% elif g.access=='allow' %}Always allow{% else %}Approval required{% endif %}
      {% endif %}
    </td>
  </tr>
  {% endfor %}
  </table>
  {% if policy_admin %}
  <button type="submit">Save group policy</button>
  {% endif %}
</form>
{% if policy_admin %}
<form method="post" action="{{ url_for('policy_reload_enforcement') }}" class="card"
      style="margin-top:1rem;border-color:#e8c4a0;background:#fffaf5"
      onsubmit="return confirmPolicyReload(this);">
  <input type="hidden" name="tab" value="policy">
  <input type="hidden" name="confirm_reload" value="1">
  <h3 style="margin-top:0;font-size:1rem">Apply policy to DefenseClaw</h3>
  <p class="hint"><b>Warning:</b> merges <code>ios-xe-policy.yaml</code> into the DefenseClaw rule pack and
  <b>restarts the DefenseClaw sidecar</b> so chat inspect and MCP enforcement pick up deny/always_block changes.
  In-flight agent sessions may be interrupted briefly.</p>
  <label style="font-weight:normal;display:flex;align-items:center;gap:.45rem;margin:.65rem 0">
    <input type="checkbox" name="reload_openclaw" value="1">
    Also restart OpenClaw gateway (Control UI / chat — longer blip)
  </label>
  <button type="submit" class="btn-warn" style="background:#c0392b">Reload policy &amp; restart gateways</button>
</form>
<script>
function confirmPolicyReload(form){
  var openclaw=form.querySelector('input[name=reload_openclaw]').checked;
  var msg='Merge ios-xe-policy.yaml into DefenseClaw and restart the DefenseClaw sidecar?';
  if(openclaw){ msg+='\\n\\nOpenClaw gateway will also restart.'; }
  msg+='\\n\\nActive sessions may be interrupted.';
  return window.confirm(msg);
}
</script>
{% endif %}
<p class="hint">Policy file: <code>{{ policy_path }}</code>.
Save updates access modes locally; use <b>Reload policy</b> after deny changes so DefenseClaw inspect rules match.
Host fallback: <code>bash admin-access/refresh-clawlab-policies.sh --preserve-access</code></p>
{% endif %}
</div>
</body></html>
"""


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

def tags_for_display(device: dict) -> str:
    """Comma-separated tags for staging editor default value."""
    tags = device.get("tags")
    if isinstance(tags, list):
        return ", ".join(str(t) for t in tags if str(t).strip())
    if isinstance(tags, str) and tags.strip():
        return tags
    return ", ".join(discovery_import.build_tags(device))


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
<p><a href="{{ url_for('index', tab='hosts') }}">&larr; back to hosts</a></p>
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


def _active_tab() -> str:
    tab = (request.args.get("tab") or request.form.get("tab") or "hosts").strip().lower()
    return tab if tab in ("hosts", "discovery", "changes", "policy") else "hosts"


def _changes_redirect(msg: str, *, err: bool = False, change_id: str | None = None):
    kwargs: dict[str, str] = {"tab": "changes", "msg": msg}
    if err:
        kwargs["err"] = "1"
    if change_id:
        kwargs["change"] = change_id
    return redirect(url_for("index", **kwargs))


def _policy_redirect(msg: str, *, err: bool = False):
    return redirect(url_for("index", tab="policy", msg=msg, err="1" if err else None))


def _get_host_entry(name: str) -> dict:
    cfg = load_config()
    hosts = cfg.get("hosts", {})
    if name not in hosts:
        raise ValueError(f"Unknown host '{name}'. Known: {', '.join(sorted(hosts))}")
    return hosts[name]


def _host_platform(h: dict) -> str:
    return str(h.get("platform", "linux") or "linux").strip().lower()


def _ensure_network_apply() -> None:
    global _network_apply_ready
    if _network_apply_ready or network_apply is None:
        return
    import server as srv

    network_apply.configure(
        get_host=srv._get_host,
        platform_fn=srv._platform,
        netmiko_type_fn=srv._netmiko_type,
        expand_fn=srv._expand,
        connect_timeout=int(srv.CONNECT_TIMEOUT),
        command_timeout=int(srv.COMMAND_TIMEOUT),
    )
    _network_apply_ready = True


def _gui_user() -> str:
    if claw_auth:
        u = claw_auth.current_user()
        if u and u.get("username"):
            return str(u["username"])
    return (os.environ.get("SSH_OPS_GUI_USER") or "gui-operator").strip() or "gui-operator"


def _gui_role() -> str:
    if claw_auth:
        u = claw_auth.current_user()
        if u and u.get("role"):
            return str(u["role"]).strip().lower()
    return (os.environ.get("SSH_OPS_GUI_ROLE") or "operator").strip().lower() or "operator"


def _policy_admin() -> bool:
    if rbac is None:
        return True
    if not rbac.rbac_enabled():
        return True
    return rbac.is_admin(rbac.effective_role(_gui_role(), _gui_user()))


def _require_policy_admin(action: str) -> None:
    if rbac is None:
        return
    try:
        rbac.check_policy_admin(role=_gui_role(), username=_gui_user(), action=action)
    except rbac.RbacDenied as exc:
        raise PermissionError(str(exc)) from exc


def _changes_for_gui(raw_changes: list[dict], *, viewer: str | None = None) -> list[dict]:
    """Copy changes for display with secrets redacted."""
    import ios_change as _ios

    out: list[dict] = []
    for change in raw_changes:
        cc = dict(change)
        if isinstance(cc.get("spec"), dict):
            cc["spec"] = _ios.public_spec(cc["spec"])
        if change_approval and viewer:
            cc["can_approve"] = change_approval.user_may_approve(change, viewer)
        else:
            cc["can_approve"] = change.get("status") == "proposed"
        targets = []
        for t in cc.get("targets") or []:
            if not isinstance(t, dict):
                continue
            tt = dict(t)
            redacted_apply = []
            for line in tt.get("apply") or []:
                if " secret " in str(line):
                    head, _tail = str(line).split(" secret ", 1)
                    redacted_apply.append(f"{head} secret ***")
                else:
                    redacted_apply.append(str(line))
            tt["apply"] = redacted_apply
            targets.append(tt)
        cc["targets"] = targets
        out.append(cc)
    return out


def _discovery_redirect(msg: str, *, err: bool = False):
    return redirect(url_for("index", tab="discovery", msg=msg, err="1" if err else None))


def _merge_staging(existing: list[dict], new_devices: list[dict]) -> list[dict]:
    """Merge by IP; new data wins on collision."""
    by_ip: dict[str, dict] = {}
    for d in existing:
        ip = str(d.get("ip") or "").strip()
        if ip:
            by_ip[ip] = d
    for d in new_devices:
        ip = str(d.get("ip") or "").strip()
        if ip:
            by_ip[ip] = d
    return list(by_ip.values())


def _parse_staging_form(count: int) -> list[dict]:
    f = request.form
    devices: list[dict] = []
    for i in range(count):
        ip = (f.get(f"ip_{i}") or "").strip()
        if not ip:
            continue
        raw = {
            "ip": ip,
            "hostname": f.get(f"hostname_{i}") or "",
            "model": f.get(f"model_{i}") or "",
            "ios_type": f.get(f"ios_type_{i}") or "unknown",
            "host_key": f.get(f"host_key_{i}") or "",
            "tags": f.get(f"tags_{i}") or "",
        }
        devices.append(discovery_import.normalize_staged_device(raw))
    return devices


def _is_network_host(host: dict) -> bool:
    plat = (host.get("platform") or "linux").strip().lower()
    return plat not in ("linux", "unix", "")


def _network_host_names(cfg: dict) -> list[str]:
    return [name for name, h in cfg.get("hosts", {}).items() if _is_network_host(h)]


def _tags_for_form(host: dict) -> list[str]:
    """Tags shown in the editor (auto_update managed by its checkbox)."""
    return [t for t in inventory.normalize_tags(host) if t.lower() != "auto_update"]


def _render_page(*, tab: str | None = None, msg: str | None = None, err: bool = False, **extra):
    active = tab or _active_tab()
    cfg = load_config()
    edit_name = (request.args.get("edit") or "").strip()
    edit_host = cfg["hosts"].get(edit_name, {}) if edit_name else {}
    if edit_name and not edit_host:
        edit_name = ""
    devices = discovery_import.load_staging(CONFIG_PATH)
    job_status = discovery_import.load_job(CONFIG_PATH)
    if job_status.get("status") in ("done", "error"):
        if msg is None and not request.args.get("msg"):
            msg = job_status.get("message")
        discovery_import.clear_job(CONFIG_PATH)
        job_status = {"status": "idle", "message": ""}
    with_login = set(secrets_store.hosts_with_secret("login"))
    network_names = _network_host_names(cfg)
    changes_enabled = change_store is not None and change_engine is not None
    pending_changes: list = []
    all_changes: list = []
    if changes_enabled:
        try:
            change_store.ensure_dir()
            all_changes = change_store.list_changes()
            pending_changes = [c for c in all_changes if c.get("status") == "proposed"]
            all_changes = _changes_for_gui(all_changes, viewer=_gui_user())
        except Exception:
            all_changes = []
            pending_changes = []
    policy_groups: list = []
    policy_path_str = ""
    if ios_xe_policy is not None:
        try:
            ios_xe_policy.ensure_policy_file()
            policy_groups = ios_xe_policy.list_groups_for_gui()
            policy_path_str = ios_xe_policy.policy_path()
        except Exception:
            policy_groups = []
    highlight_change = (request.args.get("change") or "").strip()
    ctx = dict(
        common_style=COMMON_STYLE,
        brand_head=BRAND_HEAD,
        tab=active,
        hosts=cfg["hosts"],
        inventory=inventory,
        discovery_import=discovery_import,
        tags_for_display=tags_for_display,
        with_secret=set(secrets_store.hosts_with_secret("sudo")),
        with_login=with_login,
        with_enable=set(secrets_store.hosts_with_secret("enable")),
        network_host_count=len(network_names),
        network_host_names=network_names,
        missing_login_count=sum(1 for n in network_names if n not in with_login),
        test_host_sel=(request.args.get("test_host") or "").strip(),
        config_path=str(CONFIG_PATH),
        msg=msg if msg is not None else request.args.get("msg"),
        err=err or request.args.get("err") == "1",
        edit_name=edit_name,
        edit_host=edit_host,
        edit_tags=_tags_for_form(edit_host),
        devices=devices,
        staging_count=len(devices),
        pending_change_count=len(pending_changes),
        changes_enabled=changes_enabled,
        changes=all_changes,
        job_status=job_status,
        defaults=_discovery_defaults(),
        netmiko_ok=run_discovery is not None,
        auth_required=os.environ.get("CLAW_AUTH_REQUIRED", "0").lower()
        in ("1", "true", "yes", "on"),
        policy_groups=policy_groups,
        policy_path=policy_path_str,
        policy_admin=_policy_admin(),
        gui_user=_gui_user(),
        gui_role=_gui_role(),
        highlight_change=highlight_change,
    )
    ctx.update(extra)
    return render_template_string(PAGE, **ctx)


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


@app.route("/webex/hooks/attachment-actions", methods=["POST"])
def webex_attachment_actions_hook():
    if webex_approval is None or change_engine is None:
        return jsonify({"ok": False, "error": "webex approval unavailable"}), 503
    body = request.get_data()
    signature = request.headers.get("X-Spark-Signature")
    if not webex_approval.verify_webhook_signature(body, signature):
        return jsonify({"ok": False, "error": "invalid webhook signature"}), 401
    result, status = webex_approval.handle_webhook_request(body)
    return jsonify(result), status


@app.route("/webex/action", methods=["GET", "POST"])
def webex_portal_action():
    """Signed portal link fallback — requires claw-auth login + valid token."""
    if webex_approval is None or change_engine is None:
        return _changes_redirect("Webex approval unavailable.", err=True)
    token = (request.args.get("token") or request.form.get("token") or "").strip()
    parsed = webex_approval.verify_action_token(token)
    if not parsed:
        return _changes_redirect("Invalid or expired approval link.", err=True)
    change_id, action = parsed
    user = _gui_user()
    if request.method == "GET":
        return render_template_string(
            """
            <!doctype html><html><head><meta charset="utf-8"><title>Confirm change {{ action }}</title>
            <style>{{ common_style }}</style></head><body>
            <div class="card">
              <h2>Confirm {{ action }} {{ change_id }}</h2>
              <p>Signed in as <b>{{ user }}</b>. Four-eyes rules still apply.</p>
              <form method="post">
                <input type="hidden" name="token" value="{{ token }}">
                <button type="submit">{{ action|title }} change</button>
                <a class="btn secondary" href="{{ url_for('index', tab='changes', change=change_id) }}">Cancel</a>
              </form>
            </div></body></html>
            """,
            common_style=COMMON_STYLE,
            action=action,
            change_id=change_id,
            user=user,
            token=token,
        )
    if action == "approve":
        result = change_engine.approve_change(change_id, approver=user, note="via signed portal link")
    else:
        result = change_engine.reject_change(change_id, approver=user, note="via signed portal link")
    webex_approval._mark_token_used(token)
    if result.get("error"):
        return _changes_redirect(result["error"], err=True)
    return _changes_redirect(f"{change_id} {action}d by {user} via portal link.")


@app.route("/")
def index():
    return _render_page()


@app.route("/discovery")
def discovery_legacy():
    """Redirect old /discovery URL to tabbed UI."""
    return redirect(url_for("index", tab="discovery", msg=request.args.get("msg")))


@app.route("/reload", methods=["POST"])
def reload_mcp():
    """Force the MCP's config hot-reload by bumping hosts.yaml's mtime."""
    try:
        os.utime(os.path.expanduser(str(CONFIG_PATH)), None)
        note = "Config refreshed — the MCP will load host changes on its next call (hot-reload)."
    except OSError as exc:
        note = f"Could not refresh config: {exc}"
    return redirect(url_for("index", tab="hosts", msg=note))


@app.route("/bulk-network-credentials", methods=["POST"])
def bulk_network_credentials():
    """Apply username and/or login/enable passwords to network hosts."""
    f = request.form
    bulk_username = (f.get("bulk_username") or "").strip()
    login_pw = f.get("login_password") or ""
    enable_pw = f.get("enable_password") or ""
    only_missing = f.get("only_missing") == "1"

    if not bulk_username and not login_pw and not enable_pw:
        return redirect(
            url_for("index", tab="hosts", msg="Provide a username and/or login password."),
        )
    if login_pw and login_pw != (f.get("login_password_confirm") or ""):
        return redirect(url_for("index", tab="hosts", msg="Login password entries did not match."))
    if enable_pw and enable_pw != (f.get("enable_password_confirm") or ""):
        return redirect(url_for("index", tab="hosts", msg="Enable password entries did not match."))
    if enable_pw and not login_pw:
        return redirect(
            url_for("index", tab="hosts", msg="Login password is required when setting enable password."),
        )

    cfg = load_config()
    network_names = _network_host_names(cfg)
    if not network_names:
        return redirect(url_for("index", tab="hosts", msg="No network hosts in inventory."))

    with_login = set(secrets_store.hosts_with_secret("login"))
    pw_targets = []
    if login_pw:
        pw_targets = [
            name for name in network_names
            if not only_missing or name not in with_login
        ]
        if not pw_targets:
            return redirect(
                url_for(
                    "index",
                    tab="hosts",
                    msg="No network hosts matched (all already have login secrets).",
                ),
            )

    user_targets = list(network_names) if bulk_username else []
    changed = False
    for name in user_targets:
        host = cfg.setdefault("hosts", {}).setdefault(name, {})
        if host.get("username") != bulk_username:
            host["username"] = bulk_username
            changed = True

    for name in pw_targets:
        secrets_store.set_secret(name, "login", login_pw)
        if enable_pw:
            secrets_store.set_secret(name, "enable", enable_pw)

    if changed:
        save_config(cfg)

    try:
        os.utime(os.path.expanduser(str(CONFIG_PATH)), None)
    except OSError:
        pass

    parts = []
    if bulk_username:
        parts.append(f"username '{bulk_username}' on {len(user_targets)} host(s)")
    if login_pw:
        scope = "missing login secret" if only_missing else "all network hosts"
        parts.append(f"passwords on {len(pw_targets)} host(s) ({scope})")
    return redirect(
        url_for(
            "index",
            tab="hosts",
            msg=f"Applied {'; '.join(parts)}.",
        ),
    )


@app.route("/test-credentials", methods=["POST"])
def test_credentials():
    name = (request.form.get("host") or "").strip()
    if not name:
        return redirect(url_for("index", tab="hosts", msg="Select a host to test.", err="1"))

    cfg = load_config()
    host = cfg.get("hosts", {}).get(name)
    if not host:
        return redirect(url_for("index", tab="hosts", msg=f"Unknown host: {name}", err="1"))

    test_login = (request.form.get("test_login") or "").strip() or None
    test_enable = (request.form.get("test_enable") or "").strip() or None
    cred_source = "entered credentials" if (test_login or test_enable) else "stored secrets"

    result = credential_test.test_host(
        name,
        host,
        login_pw=test_login,
        enable_pw=test_enable,
        cred_source=cred_source,
    )
    return redirect(
        url_for(
            "index",
            tab="hosts",
            test_host=name,
            msg=result.message,
            err="1" if not result.ok else None,
        ),
    )


@app.route("/save", methods=["POST"])
def save():
    f = request.form
    name = (f.get("name") or "").strip()
    if not name:
        return redirect(url_for("index", tab="hosts", msg="Name is required."))

    # Server-side backstop: password must match its confirmation (in case JS is
    # disabled). Nothing is saved on a mismatch.
    for pw_field, label in (("ssh_login_password", "SSH login password"),
                            ("sudo_password", "sudo password"),
                            ("login_password", "login password"),
                            ("enable_password", "enable password")):
        pw = f.get(pw_field) or ""
        if pw and pw != (f.get(pw_field + "_confirm") or ""):
            return redirect(url_for("index", tab="hosts", msg=f"{label} entries did not match — nothing saved."))

    cfg = load_config()
    host = cfg["hosts"].get(name, {})

    platform = (f.get("platform") or "linux").strip().lower()
    is_net = platform not in ("linux", "unix", "")

    host["platform"] = platform
    tags = inventory.parse_tags_field(f.get("tags") or "")
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
        for field in ("allowed_services", "use_sudo_for_restart", "use_pty", "allow_write", "auto_update"):
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
        if f.get("auto_update") == "on":
            host["auto_update"] = True
            if not any(t.lower() == "auto_update" for t in tags):
                tags.append("auto_update")
        else:
            host["auto_update"] = False
            tags = [t for t in tags if t.lower() != "auto_update"]
        ssh_login = f.get("ssh_login_password") or ""
        if ssh_login:
            secrets_store.set_secret(name, "login", ssh_login)
            notes.append("ssh login pw encrypted")
        pw = f.get("sudo_password") or ""
        if pw:
            secrets_store.set_sudo_password(name, pw)
            notes.append("sudo pw encrypted")

    if tags:
        host["tags"] = tags
    else:
        host.pop("tags", None)
    host.pop("description", None)

    cfg["hosts"][name] = host
    save_config(cfg)
    return redirect(url_for("index", tab="hosts", msg="; ".join(notes) + "."))


def _discovery_defaults() -> dict:
    return {
        "method": (request.args.get("method") or request.form.get("method") or "cdp").strip(),
        "seed": (request.args.get("seed") or request.form.get("seed") or "").strip(),
        "ip_range": (request.args.get("ip_range") or request.form.get("ip_range") or "").strip(),
        "username": (request.args.get("username") or request.form.get("username") or "netadmin").strip(),
        "max_hops": int(request.args.get("max_hops") or request.form.get("max_hops") or 5),
        "max_workers": int(request.args.get("max_workers") or request.form.get("max_workers") or 10),
    }


def _discovery_job_worker(
    *,
    method: str,
    username: str,
    password: str,
    seed: str,
    ip_range: str,
    enable_password: str | None,
    max_hops: int,
    max_workers: int,
    merge: bool,
) -> None:
    discovery_import.save_job(CONFIG_PATH, {
        "status": "running",
        "message": f"Discovery running ({method}) — connecting to seed…",
        "started_at": time.time(),
    })
    try:
        found = run_discovery(
            method=method,
            username=username,
            password=password,
            seed=seed,
            ip_range=ip_range,
            enable_password=enable_password,
            max_hops=max_hops,
            max_workers=max_workers,
        )
        if not found:
            discovery_import.save_job(CONFIG_PATH, {
                "status": "error",
                "message": (
                    "No devices discovered. Check seed IP, credentials, enable password, "
                    "and that the ssh-ops container can reach the network."
                ),
            })
            return
        if merge:
            found = _merge_staging(discovery_import.load_staging(CONFIG_PATH), found)
        discovery_import.save_staging(
            CONFIG_PATH,
            found,
            meta={"method": method, "seed": seed, "ip_range": ip_range},
        )
        importable = sum(1 for d in found if discovery_import.is_importable(d))
        discovery_import.save_job(CONFIG_PATH, {
            "status": "done",
            "message": f"Discovery complete: {len(found)} staged, {importable} importable.",
            "count": len(found),
            "reload": True,
        })
    except Exception as exc:
        discovery_import.save_job(CONFIG_PATH, {
            "status": "error",
            "message": f"Discovery failed: {exc}",
        })


@app.route("/discovery/status")
def discovery_status():
    job = discovery_import.load_job(CONFIG_PATH)
    return jsonify(job)


@app.route("/discovery/run", methods=["POST"])
def discovery_run():
    if run_discovery is None:
        return _discovery_redirect("netmiko is not available.", err=True)
    job = discovery_import.load_job(CONFIG_PATH)
    if job.get("status") == "running":
        return _discovery_redirect("Discovery already in progress.", err=True)
    f = request.form
    method = (f.get("method") or "cdp").strip()
    username = (f.get("username") or "").strip()
    password = f.get("password") or ""
    enable_password = (f.get("enable_password") or "").strip() or None
    seed = (f.get("seed") or "").strip()
    ip_range = (f.get("ip_range") or "").strip()
    merge = f.get("merge") == "1"
    try:
        max_hops = max(1, min(20, int(f.get("max_hops") or 5)))
        max_workers = max(1, min(50, int(f.get("max_workers") or 10)))
    except ValueError:
        return _discovery_redirect("Invalid max_hops or max_workers.", err=True)
    if not username or not password:
        return _discovery_redirect("Username and password are required.", err=True)
    if method in ("cdp", "lldp") and not seed:
        return _discovery_redirect("Seed device IP is required for CDP/LLDP discovery.", err=True)
    if method == "range" and not (ip_range or seed):
        return _discovery_redirect("IP range (CIDR) is required for range discovery.", err=True)

    thread = threading.Thread(
        target=_discovery_job_worker,
        kwargs={
            "method": method,
            "username": username,
            "password": password,
            "seed": seed,
            "ip_range": ip_range,
            "enable_password": enable_password,
            "max_hops": max_hops,
            "max_workers": max_workers,
            "merge": merge,
        },
        daemon=True,
    )
    thread.start()
    return _discovery_redirect("Discovery started — status updates below.")


@app.route("/discovery/upload", methods=["POST"])
def discovery_upload():
    upload = request.files.get("yaml_file")
    if not upload or not upload.filename:
        return _discovery_redirect("No file uploaded.", err=True)
    merge = request.form.get("merge") == "1"
    try:
        content = upload.read().decode("utf-8", errors="replace")
        found = discovery_import.parse_upload_yaml(content)
    except yaml.YAMLError as exc:
        return _discovery_redirect(f"Invalid YAML: {exc}", err=True)
    if not found:
        return _discovery_redirect("No devices found in file.", err=True)
    if merge:
        found = _merge_staging(discovery_import.load_staging(CONFIG_PATH), found)
    discovery_import.save_staging(CONFIG_PATH, found, meta={"source": "upload"})
    importable = sum(1 for d in found if discovery_import.is_importable(d))
    return _discovery_redirect(f"Loaded {len(found)} device(s), {importable} importable.")


@app.route("/discovery/staging/save", methods=["POST"])
def discovery_staging_save():
    try:
        count = int(request.form.get("device_count") or 0)
    except ValueError:
        count = 0
    devices = _parse_staging_form(count)
    if count and not devices:
        return _discovery_redirect("Each row needs an IP address.", err=True)
    discovery_import.save_staging(CONFIG_PATH, devices)
    return _discovery_redirect(f"Saved {len(devices)} staged device(s).")


@app.route("/discovery/staging/add", methods=["POST"])
def discovery_staging_add():
    f = request.form
    device = discovery_import.normalize_staged_device({
        "ip": f.get("ip") or "",
        "hostname": f.get("hostname") or "",
        "model": f.get("model") or "",
        "ios_type": f.get("ios_type") or "unknown",
        "host_key": f.get("host_key") or "",
        "tags": f.get("tags") or "",
    })
    if not device.get("ip"):
        return _discovery_redirect("IP address is required to add a device.", err=True)
    devices = discovery_import.load_staging(CONFIG_PATH)
    devices.append(device)
    discovery_import.save_staging(CONFIG_PATH, devices)
    return _discovery_redirect(f"Added {device['ip']} to staging.")


@app.route("/discovery/staging/remove/<int:idx>", methods=["POST"])
def discovery_staging_remove(idx: int):
    devices = discovery_import.load_staging(CONFIG_PATH)
    if 0 <= idx < len(devices):
        removed = devices.pop(idx)
        discovery_import.save_staging(CONFIG_PATH, devices)
        return _discovery_redirect(f"Removed {removed.get('ip', idx + 1)} from staging.")
    return _discovery_redirect("Device not found in staging.", err=True)


@app.route("/discovery/import", methods=["POST"], endpoint="discovery_import")
def discovery_import_route():
    devices = discovery_import.load_staging(CONFIG_PATH)
    if not devices:
        return _discovery_redirect("No staged devices — run discovery or upload YAML first.", err=True)
    f = request.form
    username = (f.get("import_username") or "").strip()
    login_pw = f.get("import_login") or ""
    enable_pw = (f.get("import_enable") or "").strip() or None
    if not username or not login_pw:
        return _discovery_redirect("Import username and login password required.", err=True)
    selected = []
    for raw in f.getlist("sel"):
        try:
            selected.append(int(raw))
        except ValueError:
            continue
    if not selected:
        return _discovery_redirect("Select at least one device.", err=True)
    cfg = load_config()
    added, skipped, messages = discovery_import.merge_selected_into_hosts(
        cfg,
        devices,
        selected,
        username=username,
        login_password=login_pw,
        enable_password=enable_pw,
        secrets_store=secrets_store,
    )
    save_config(cfg)
    try:
        os.utime(os.path.expanduser(str(CONFIG_PATH)), None)
    except OSError:
        pass
    remaining = [d for i, d in enumerate(devices) if i not in set(selected)]
    if remaining:
        discovery_import.save_staging(CONFIG_PATH, remaining)
    else:
        discovery_import.clear_staging(CONFIG_PATH)
    summary = f"Imported {added} host(s), skipped {skipped}."
    if messages:
        summary += " " + "; ".join(messages[:6])
        if len(messages) > 6:
            summary += f" (+{len(messages) - 6} more)"
    return redirect(url_for("index", tab="hosts", msg=summary))


@app.route("/discovery/clear", methods=["POST"])
def discovery_clear():
    discovery_import.clear_staging(CONFIG_PATH)
    return _discovery_redirect("Staging cleared.")


@app.route("/changes/approve", methods=["POST"])
def change_approve():
    if change_engine is None:
        return _changes_redirect("Change engine unavailable.", err=True)
    cid = (request.form.get("change_id") or "").strip()
    if not cid:
        return _changes_redirect("Missing change id.", err=True)
    user = _gui_user()
    result = change_engine.approve_change(cid, approver=user)
    if result.get("error"):
        return _changes_redirect(result["error"], err=True)
    return _changes_redirect(
        f"Approved {cid} by {user}. Another user proposed it (four-eyes satisfied)."
    )


@app.route("/changes/reject", methods=["POST"])
def change_reject():
    if change_store is None:
        return _changes_redirect("Change store unavailable.", err=True)
    cid = (request.form.get("change_id") or "").strip()
    note = (request.form.get("note") or "").strip()
    if not cid:
        return _changes_redirect("Missing change id.", err=True)
    result = change_engine.reject_change(cid, approver=_gui_user(), note=note)
    if result.get("error"):
        return _changes_redirect(result["error"], err=True)
    return _changes_redirect(f"Rejected {cid}.")


@app.route("/changes/apply", methods=["POST"])
def change_apply():
    if change_engine is None:
        return _changes_redirect("Change engine unavailable.", err=True)
    cid = (request.form.get("change_id") or "").strip()
    if not cid:
        return _changes_redirect("Missing change id.", err=True)
    _ensure_network_apply()
    result = change_engine.apply_change(cid, actor=_gui_user())
    if result.get("error"):
        stage = result.get("failure_stage")
        detail = result["error"]
        if stage:
            detail = f"{detail} (failed at {stage})"
        return _changes_redirect(f"{cid}: {detail}", err=True, change_id=cid)
    if result.get("status") != "applied":
        stage = result.get("failure_stage") or "unknown"
        return _changes_redirect(
            f"{cid} finished with status={result.get('status')} (stage={stage}).",
            err=True,
            change_id=cid,
        )
    return _changes_redirect(f"{cid} applied successfully.", change_id=cid)


@app.route("/changes/rollback", methods=["POST"])
def change_rollback():
    if change_engine is None:
        return _changes_redirect("Change engine unavailable.", err=True)
    cid = (request.form.get("change_id") or "").strip()
    if not cid:
        return _changes_redirect("Missing change id.", err=True)
    _ensure_network_apply()
    result = change_engine.rollback_change(cid, actor=_gui_user())
    if result.get("error"):
        return _changes_redirect(f"{cid}: {result['error']}", err=True)
    return _changes_redirect(f"{cid} rollback finished (status={result.get('status')}).")


@app.route("/changes/propose-lines", methods=["POST"])
def change_propose_lines():
    if change_engine is None:
        return _changes_redirect("Change engine unavailable.", err=True)
    f = request.form
    host = (f.get("host") or "").strip()
    group = (f.get("group") or "").strip()
    intent = (f.get("intent") or "").strip()
    raw_lines = f.get("lines") or ""
    lines = [ln.rstrip() for ln in raw_lines.splitlines() if ln.strip()]
    if not host:
        return _changes_redirect("Host is required.", err=True)
    if not lines:
        return _changes_redirect("At least one config line is required.", err=True)
    result = change_engine.propose_change(
        host=host,
        change_type="ios_config_lines",
        spec={"lines": lines, "group": group},
        intent=intent,
        created_by=_gui_user(),
        get_host=_get_host_entry,
        platform_fn=_host_platform,
    )
    if result.get("error"):
        detail = result.get("errors") or result["error"]
        return _changes_redirect(f"Proposal failed: {detail}", err=True)
    if result.get("status") == "approved":
        return _changes_redirect(
            f"Proposed {result.get('change_id')} ({group}) — auto-approved; apply when ready."
        )
    return _changes_redirect(
        f"Proposed {result.get('change_id')} ({group}) — approve before apply."
    )


@app.route("/policy/groups", methods=["POST"])
def policy_save_groups():
    if ios_xe_policy is None:
        return _policy_redirect("Policy module unavailable.", err=True)
    try:
        _require_policy_admin("Policy group edits")
    except PermissionError as exc:
        return _policy_redirect(str(exc), err=True)
    updates: dict[str, str] = {}
    for key, val in request.form.items():
        if key.startswith("access_"):
            updates[key[7:]] = val
    if not updates:
        return _policy_redirect("No group updates submitted.", err=True)
    try:
        ios_xe_policy.update_groups_access(updates)
    except (ValueError, OSError) as exc:
        return _policy_redirect(str(exc), err=True)
    return _policy_redirect(
        "Policy group access updated. Use “Reload policy & restart gateways” "
        "if you changed Always deny modes."
    )


@app.route("/policy/reload", methods=["POST"])
def policy_reload_enforcement():
    if policy_reload is None:
        return _policy_redirect("Policy reload module unavailable.", err=True)
    try:
        _require_policy_admin("Policy enforcement reload")
    except PermissionError as exc:
        return _policy_redirect(str(exc), err=True)
    if request.form.get("confirm_reload") != "1":
        return _policy_redirect("Reload cancelled (confirmation required).", err=True)
    reload_openclaw = request.form.get("reload_openclaw") == "1"
    try:
        ok, message = policy_reload.reload_enforcement(reload_openclaw=reload_openclaw)
    except policy_reload.PolicyReloadError as exc:
        return _policy_redirect(str(exc), err=True)
    except Exception as exc:  # noqa: BLE001
        return _policy_redirect(f"Reload failed: {exc}", err=True)
    if not ok:
        return _policy_redirect(message, err=True)
    return _policy_redirect(message)


@app.route("/changes/propose", methods=["POST"])
def change_propose():
    if change_engine is None:
        return _changes_redirect("Change engine unavailable.", err=True)
    f = request.form
    host = (f.get("host") or "").strip()
    username = (f.get("username") or "").strip()
    password = f.get("password") or ""
    password_confirm = f.get("password_confirm") or ""
    action = (f.get("action") or "create").strip().lower()
    intent = (f.get("intent") or "").strip()
    if not host:
        return _changes_redirect("Host is required.", err=True)
    if action == "create" and password != password_confirm:
        return _changes_redirect("Password entries did not match.", err=True)
    try:
        privilege = int(f.get("privilege") or 15)
    except ValueError:
        return _changes_redirect("Privilege must be a number.", err=True)
    spec = {
        "username": username,
        "action": action,
        "privilege": privilege,
    }
    if action == "create":
        spec["password"] = password
    result = change_engine.propose_change(
        host=host,
        change_type="ios_local_user",
        spec=spec,
        intent=intent,
        created_by=_gui_user(),
        get_host=_get_host_entry,
        platform_fn=_host_platform,
    )
    if result.get("error"):
        detail = result.get("errors") or result["error"]
        return _changes_redirect(f"Proposal failed: {detail}", err=True)
    return _changes_redirect(
        f"Proposed {result.get('change_id')} — approve it before apply."
    )


@app.route("/delete", methods=["POST"])
def delete():
    name = (request.form.get("name") or "").strip()
    cfg = load_config()
    if name in cfg["hosts"]:
        del cfg["hosts"][name]
        save_config(cfg)
    secrets_store.delete_all_secrets(name)
    return redirect(url_for("index", tab="hosts", msg=f"deleted {name}."))


if __name__ == "__main__":
    port = int(os.environ.get("SSH_OPS_GUI_PORT", 8765))
    # Defaults to loopback. In a container set SSH_OPS_GUI_HOST=0.0.0.0 and
    # publish the port ONLY to the host's loopback, e.g. -p 127.0.0.1:8765:8765,
    # so it still isn't reachable from the network.
    host = os.environ.get("SSH_OPS_GUI_HOST", "127.0.0.1")
    app.run(host=host, port=port, debug=False, threaded=True)
