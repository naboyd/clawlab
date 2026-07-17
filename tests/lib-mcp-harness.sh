#!/usr/bin/env bash
# Shared MCP harness helpers for clawlab test scripts.
# Source from policy-test.sh / scenario-*.sh — do not execute directly.
set -uo pipefail

MCP_LAST_ERR=""

# Portable timeout (macOS lacks GNU timeout by default).
run_timeout() {
  local secs="$1"
  shift
  if command -v timeout >/dev/null 2>&1; then
    timeout "$secs" "$@"
  elif command -v gtimeout >/dev/null 2>&1; then
    gtimeout "$secs" "$@"
  else
    perl -e 'alarm shift; exec @ARGV' "$secs" "$@"
  fi
}

mcp_ssh_ops_data_dir() {
  printf '%s\n' "${SSH_OPS_DATA:-$HOME/.clawlab/ssh-ops/data}"
}

# Source of truth for MCP bearer auth (matches ssh-ops MCP server + Admin UI).
mcp_load_ssh_ops_token() {
  local repo="${REPO:-}" data token py
  data="$(mcp_ssh_ops_data_dir)"
  [[ -f "$data/.env" && -f "$data/master.key" ]] || return 1
  if [[ -n "${CLAW_PYTHON:-}" && -x "$CLAW_PYTHON" ]]; then
    py="$CLAW_PYTHON"
  elif [[ -x "$HOME/.clawlab/venv/bin/python" ]]; then
    py="$HOME/.clawlab/venv/bin/python"
  else
    py="python3"
  fi
  token="$(
    SSH_OPS_CONFIG="$data/hosts.yaml" \
    SSH_OPS_ENV="$data/.env" \
    SSH_OPS_KEYFILE="$data/master.key" \
    PYTHONPATH="${repo}/ssh-ops-mcp" \
    "$py" -c 'import secrets_store; print(secrets_store.ensure_mcp_token())' 2>/dev/null \
    || true
  )"
  [[ -n "$token" ]] || return 1
  printf 'Bearer %s' "$token"
}

mcp_sync_openclaw_auth() {
  local auth="${1:-}"
  [[ -n "$auth" ]] || return 1
  python3 - "$auth" <<'PY' 2>/dev/null || return 1
import json, os, sys
auth = sys.argv[1]
p = os.path.expanduser("~/.openclaw/openclaw.json")
if not os.path.isfile(p):
    raise SystemExit(1)
d = json.load(open(p))
entry = d.setdefault("mcp", {}).setdefault("servers", {}).setdefault("ssh-ops", {})
entry.setdefault("url", "http://127.0.0.1:8766/mcp")
entry.setdefault("transport", "streamable-http")
entry["headers"] = {"Authorization": auth}
json.dump(d, open(p, "w"), indent=1)
print("synced openclaw.json ssh-ops MCP auth")
PY
}

# Load MCP auth/url from ssh-ops secrets (preferred) then openclaw.json.
mcp_load_config() {
  local oc_auth="" file_auth=""
  oc_auth=$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.openclaw/openclaw.json')))['mcp']['servers']['ssh-ops']['headers']['Authorization'])" 2>/dev/null || true)
  file_auth=$(mcp_load_ssh_ops_token || true)
  if [[ -n "$file_auth" ]]; then
    MCP_AUTH="$file_auth"
    if [[ -n "$oc_auth" && "$oc_auth" != "$file_auth" ]]; then
      mcp_sync_openclaw_auth "$file_auth" >/dev/null || true
    fi
  else
    MCP_AUTH="$oc_auth"
  fi
  MCP_URL=$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.openclaw/openclaw.json')))['mcp']['servers']['ssh-ops']['url'])" 2>/dev/null || true)
  if [ -n "$MCP_URL" ] && echo "$MCP_URL" | grep -q ':8767'; then
    local code
    code=$(curl -sk -m3 -o /dev/null -w '%{http_code}' -X POST "$MCP_URL" \
      -H "Authorization: $MCP_AUTH" \
      -H 'Content-Type: application/json' \
      -H 'Accept: application/json, text/event-stream' \
      -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"harness","version":"1"}}}' \
      2>/dev/null || echo 000)
    if [ "$code" = "000" ] || [ "$code" = "502" ] || [ "$code" = "500" ]; then
      MCP_URL="${SSH_OPS_MCP_URL:-http://127.0.0.1:8766/mcp}"
    fi
  fi
  if [ -z "$MCP_URL" ]; then
    MCP_URL="${SSH_OPS_MCP_URL:-http://127.0.0.1:8766/mcp}"
  fi
}

# Parse list_hosts MCP JSON -> newline "name<TAB>kind" (linux|network).
mcp_list_hosts_rows() {
  local r="${1:-}"
  [[ -n "$r" ]] || return 1
  MCP_JSON="$r" python3 - <<'PY'
import json, os
raw = os.environ.get("MCP_JSON", "")
try:
    d = json.loads(raw)
except json.JSONDecodeError:
    raise SystemExit(1)
hosts = []

def ingest(rows):
    if not isinstance(rows, list):
        return
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        if not name:
            continue
        kind = str(row.get("kind") or "").strip().lower()
        if not kind:
            plat = str(row.get("platform") or "linux").strip().lower()
            kind = "network" if plat not in ("linux", "unix", "") else "linux"
        hosts.append((name, kind))

result = d.get("result") or {}
if isinstance(result, list):
    ingest(result)
else:
    for block in result.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            try:
                ingest(json.loads(block.get("text") or "[]"))
            except json.JSONDecodeError:
                pass
            break
    sc = result.get("structuredContent")
    if isinstance(sc, list):
        ingest(sc)
    elif isinstance(sc, dict):
        ingest(sc.get("hosts") or sc.get("result") or [])
if not hosts and os.environ.get("MCP_DEBUG"):
    import sys
    print(f"debug: unparsed keys={list(d.keys())}", file=sys.stderr)
    if isinstance(result, dict):
        print(f"debug: result keys={list(result.keys())}", file=sys.stderr)
for name, kind in hosts:
    print(f"{name}\t{kind}")
PY
}

mcp_list_host_names() {
  mcp_session_start
  local r
  r=$(mcp_tool_call list_hosts '{}')
  mcp_list_hosts_rows "$r" | cut -f1
}

mcp_pick_linux_host() {
  local prefer="${1:-}"
  mcp_session_start
  local r row name kind
  r=$(mcp_tool_call list_hosts '{}')
  if [[ -n "$prefer" ]] && mcp_list_hosts_rows "$r" | awk -F '\t' -v p="$prefer" '$1==p && $2=="linux"{found=1} END{exit !found}'; then
    if [[ "$(mcp_run_command_verdict "$prefer" "true")" == allow ]]; then
      echo "$prefer"
      return 0
    fi
  fi
  while IFS=$'\t' read -r name kind; do
    [[ "$kind" == linux ]] || continue
    if [[ "$(mcp_run_command_verdict "$name" "true")" == allow ]]; then
      echo "$name"
      return 0
    fi
  done < <(mcp_list_hosts_rows "$r" || true)
  return 1
}

mcp_pick_network_host() {
  local prefer="${1:-}"
  mcp_session_start
  local r
  r=$(mcp_tool_call list_hosts '{}')
  if [[ -n "$prefer" ]] && mcp_list_hosts_rows "$r" | awk -F '\t' -v p="$prefer" '$1==p && $2=="network"{found=1} END{exit !found}'; then
    echo "$prefer"
    return 0
  fi
  mcp_list_hosts_rows "$r" | awk -F '\t' '$2=="network"{print $1; exit}'
}

_mcp_inventory_paths() {
  local -a paths=()
  if [ -n "${SSH_OPS_CONFIG:-}" ]; then
    paths+=("$SSH_OPS_CONFIG")
  fi
  paths+=(
    "$HOME/.clawlab/ssh-ops/data/hosts.yaml"
    "$HOME/ssh_ops_mcp/data/hosts.yaml"
  )
  printf '%s\n' "${paths[@]}"
}

mcp_discover_linux_host() {
  local paths
  paths=$(_mcp_inventory_paths)
  SSH_OPS_CONFIG="${SSH_OPS_CONFIG:-}" MCP_INVENTORY_PATHS="$paths" python3 - <<'PY' 2>/dev/null
import os
from pathlib import Path
try:
    import yaml
except ImportError:
    raise SystemExit(0)
for raw in (os.environ.get("MCP_INVENTORY_PATHS") or "").splitlines():
    path = Path(raw.strip()).expanduser()
    if not path.is_file():
        continue
    cfg = yaml.safe_load(path.read_text()) or {}
    for name, host in (cfg.get("hosts") or {}).items():
        plat = str(host.get("platform", "linux") or "linux").strip().lower()
        if plat in ("linux", "unix", ""):
            print(name)
            raise SystemExit(0)
PY
}

mcp_inventory_ready() {
  local paths
  paths=$(_mcp_inventory_paths)
  if SSH_OPS_CONFIG="${SSH_OPS_CONFIG:-}" MCP_INVENTORY_PATHS="$paths" python3 - <<'PY' 2>/dev/null
import os, sys
from pathlib import Path
try:
    import yaml
except ImportError:
    sys.exit(1)
for raw in (os.environ.get("MCP_INVENTORY_PATHS") or "").splitlines():
    path = Path(raw.strip()).expanduser()
    if not path.is_file():
        continue
    cfg = yaml.safe_load(path.read_text()) or {}
    hosts = cfg.get("hosts") or {}
    if isinstance(hosts, dict) and len(hosts) > 0:
        raise SystemExit(0)
raise SystemExit(1)
PY
  then
    return 0
  fi
  # Fall back to live MCP inventory (discovery may have imported network-only hosts).
  [[ -n "${MCP_AUTH:-}" && -n "${MCP_URL:-}" ]] || return 1
  mcp_session_start
  local r
  r=$(mcp_tool_call list_hosts '{}')
  [[ -n "$r" ]] || return 1
  mcp_list_hosts_rows "$r" | grep -q .
}

mcp_discover_net_host() {
  local paths
  paths=$(_mcp_inventory_paths)
  SSH_OPS_CONFIG="${SSH_OPS_CONFIG:-}" MCP_INVENTORY_PATHS="$paths" python3 - <<'PY' 2>/dev/null
import os
from pathlib import Path
try:
    import yaml
except ImportError:
    raise SystemExit(0)
for raw in (os.environ.get("MCP_INVENTORY_PATHS") or "").splitlines():
    path = Path(raw.strip()).expanduser()
    if not path.is_file():
        continue
    cfg = yaml.safe_load(path.read_text()) or {}
    for name, host in (cfg.get("hosts") or {}).items():
        plat = str(host.get("platform", "linux") or "linux").strip().lower()
        if plat not in ("linux", "unix", ""):
            print(name)
            raise SystemExit(0)
PY
}

mcp_host_known() {
  local host="${1:-}"
  [ -n "$host" ] || return 1
  mcp_session_start
  local r
  r=$(mcp_tool_call list_hosts '{}')
  mcp_list_hosts_rows "$r" | awk -F '\t' -v h="$host" '$1==h{found=1} END{exit !found}'
}

# Extract JSON object from MCP streamable-http (SSE) or plain JSON body.
mcp_parse_response_body() {
  local body="${1:-}"
  [[ -n "$body" && -f "$body" ]] || return 1
  local line
  line="$(sed -n 's/^data: //p' "$body" | grep -E '"id"[[:space:]]*:[[:space:]]*2' | tail -1)"
  [[ -z "$line" ]] && line="$(sed -n 's/^data: //p' "$body" | grep '"result"' | tail -1)"
  [[ -z "$line" ]] && line="$(sed -n 's/^data: //p' "$body" | tail -1)"
  if [[ -z "$line" ]]; then
    line="$(python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1]))))' "$body" 2>/dev/null || true)"
  fi
  [[ -n "$line" ]] || return 1
  printf '%s' "$line"
}

mcp_http_headers() {
  local user="${1:-}" role="${2:-}"
  MCP_HTTP_HDR=(
    -H "Authorization: $MCP_AUTH"
    -H 'Content-Type: application/json'
    -H 'Accept: application/json, text/event-stream'
  )
  [[ -n "$MCP_SESSION_ID" ]] && MCP_HTTP_HDR+=(-H "Mcp-Session-Id: $MCP_SESSION_ID")
  [[ -n "$user" ]] && MCP_HTTP_HDR+=(-H "X-Auth-User: $user" -H "X-Forwarded-User: $user")
  [[ -n "$role" ]] && MCP_HTTP_HDR+=(-H "X-Auth-Role: $role")
}

mcp_session_start() {
  local user="${1:-}" role="${2:-}"
  MCP_SESSION_ID=""
  local hf body code
  hf="$(mktemp)"
  body="$(mktemp)"
  mcp_http_headers "$user" "$role"
  code="$(curl -sS -m12 -D "$hf" -o "$body" -w '%{http_code}' -X POST "$MCP_URL" "${MCP_HTTP_HDR[@]}" \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"harness","version":"1"}}}' \
    2>"${body}.err" || echo 000)"
  MCP_SESSION_ID="$(grep -i '^mcp-session-id:' "$hf" | awk '{print $2}' | tr -d '\r')"
  if [[ "$code" != "200" && "$code" != "202" ]]; then
    MCP_LAST_ERR="MCP initialize HTTP ${code} at ${MCP_URL}$(head -c 120 "${body}.err" 2>/dev/null | sed 's/^/ — /')"
    rm -f "$hf" "$body" "${body}.err"
    return 1
  fi
  if [[ -z "$MCP_SESSION_ID" ]]; then
    MCP_LAST_ERR="MCP initialize missing Mcp-Session-Id header (got HTTP ${code})"
    rm -f "$hf" "$body" "${body}.err"
    return 1
  fi
  mcp_http_headers "$user" "$role"
  curl -sS -m10 -o /dev/null -X POST "$MCP_URL" "${MCP_HTTP_HDR[@]}" \
    -d '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
    2>/dev/null || true
  rm -f "$hf" "$body" "${body}.err"
  return 0
}

# mcp_tool_call TOOL JSON_ARGS [USER] [ROLE]  -> last JSON line from MCP response
mcp_tool_call() {
  local tool="$1" args="$2" user="${3:-}" role="${4:-}"
  local body payload line
  payload="$(jq -n --arg tool "$tool" --argjson args "$args" \
    '{jsonrpc:"2.0",id:2,method:"tools/call",params:{name:$tool,arguments:$args}}')" \
    || { MCP_LAST_ERR="invalid MCP tool args for $tool"; return 1; }
  body="$(mktemp)"
  mcp_http_headers "$user" "$role"
  if ! curl -sS -m30 -o "$body" -X POST "$MCP_URL" "${MCP_HTTP_HDR[@]}" -d "$payload" 2>"${body}.err"; then
    MCP_LAST_ERR="MCP tools/call curl failed for $tool ($(tr '\n' ' ' <"${body}.err" | head -c 120))"
    rm -f "$body" "${body}.err"
    return 1
  fi
  line="$(mcp_parse_response_body "$body" || true)"
  rm -f "$body" "${body}.err"
  [[ -n "$line" ]] || { MCP_LAST_ERR="MCP tools/call $tool returned empty body"; return 1; }
  printf '%s' "$line"
}

mcp_probe_ready() {
  MCP_LAST_ERR=""
  mcp_session_start || {
    echo "${MCP_LAST_ERR:-MCP session init failed at $MCP_URL}"
    return 1
  }
  local r
  r="$(mcp_tool_call list_hosts '{}' || true)"
  if [[ -z "$r" ]]; then
    echo "${MCP_LAST_ERR:-MCP unreachable at $MCP_URL (is ssh-ops MCP up? podctl --status)}"
    return 1
  fi
  if echo "$r" | grep -qiE '"error"|unauthorized|401|403'; then
    if echo "$r" | grep -qi unauthorized; then
      echo "MCP auth failed — run: bash install/local-full-ctl.sh restart"
    else
      echo "MCP error: $(echo "$r" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('error',{}).get('message',d))" 2>/dev/null || echo "$r" | head -c 120)"
    fi
    return 1
  fi
  mcp_list_hosts_rows "$r" | grep -q . || {
    echo "MCP list_hosts returned no inventory (empty hosts.yaml?)"
    return 1
  }
  return 0
}

mcp_host_reachable() {
  local host="${1:-}"
  [ -n "$host" ] || return 1
  mcp_host_known "$host" || return 1
  mcp_session_start
  [ "$(mcp_run_command_verdict "$host" "true")" = allow ]
}

mcp_response_is_rbac_block() {
  echo "$1" | grep -qiE \
    'sensitive_read|admin_required|requires admin role|requires role .admin.|RBAC_DENIED|missing_identity|identity_mismatch|does not match verified user'
}

mcp_response_is_allowlist_block() {
  echo "$1" | grep -qiE 'allowlist|not on the|not permitted|rejected'
}

# mcp_rbac_verdict USER ROLE HOST COMMAND  -> allow|block|err
mcp_rbac_verdict() {
  local user="$1" role="$2" host="$3" cmd="$4" r
  r=$(mcp_tool_call run_command \
    "$(jq -n --arg h "$host" --arg c "$cmd" '{host:$h,command:$c}')" \
    "$user" "$role")
  if mcp_response_is_rbac_block "$r"; then
    echo block
  elif echo "$r" | grep -q '"exit_code"'; then
    echo allow
  elif mcp_response_is_allowlist_block "$r"; then
    echo block
  elif echo "$r" | grep -q '"error"'; then
    echo err
  else
    echo err
  fi
}

mcp_run_command_verdict() {
  local r
  r=$(mcp_tool_call run_command "$(jq -n --arg h "$1" --arg c "$2" '{host:$h,command:$c}')")
  if mcp_response_is_rbac_block "$r" || mcp_response_is_allowlist_block "$r"; then
    echo block
  elif echo "$r" | grep -q '"exit_code"'; then
    echo allow
  elif echo "$r" | grep -q '"error"'; then
    echo err
  else
    echo err
  fi
}

# mcp_propose_ios_verdict HOST GROUP JSON_LINES USER ROLE -> allow|block|err
# allow = proposal accepted (change_id or proposed status); block = policy/RBAC rejection
mcp_propose_ios_verdict() {
  local host="$1" group="$2" lines_json="$3" user="${4:-harness-admin}" role="${5:-admin}"
  local r
  r=$(mcp_tool_call propose_change \
    "$(jq -n \
      --arg h "$host" \
      --arg g "$group" \
      --arg user "$user" \
      --argjson lines "$lines_json" \
      '{host:$h,change_type:"ios_config_lines",requested_by:$user,intent:"harness ios_config_lines",spec:{group:$g,lines:$lines}}')" \
    "$user" "$role")
  if mcp_response_is_rbac_block "$r"; then
    echo block
  elif echo "$r" | grep -qiE 'Proposal rejected|always deny|blocked|not allowed|Unknown allow group'; then
    echo block
  elif echo "$r" | grep -qE 'change_id|"status"\s*:\s*"proposed"|auto-approved|"risk"'; then
    echo allow
  elif echo "$r" | grep -q '"error"'; then
    echo block
  else
    echo err
  fi
}
