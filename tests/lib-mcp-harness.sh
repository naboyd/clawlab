#!/usr/bin/env bash
# Shared MCP harness helpers for clawlab test scripts.
# Source from policy-test.sh / scenario-*.sh — do not execute directly.
set -uo pipefail

# Load MCP auth/url from openclaw.json; fall back to direct :8766 when identity proxy is down.
mcp_load_config() {
  MCP_AUTH=$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.openclaw/openclaw.json')))['mcp']['servers']['ssh-ops']['headers']['Authorization'])" 2>/dev/null || true)
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
      MCP_URL="${SSH_OPS_MCP_URL:-https://192.168.128.93:8766/mcp}"
    fi
  fi
}

mcp_discover_net_host() {
  REPO_ROOT="${REPO:-}" SSH_OPS_CONFIG="${SSH_OPS_CONFIG:-}" python3 - <<'PY' 2>/dev/null
import os
from pathlib import Path
try:
    import yaml
except ImportError:
    raise SystemExit(0)
repo = os.environ.get("REPO_ROOT", "")
candidates = [
    Path(os.environ.get("SSH_OPS_CONFIG", "")).expanduser(),
    Path.home() / "ssh_ops_mcp/data/hosts.yaml",
]
if repo:
    candidates.append(Path(repo) / "ssh-ops-mcp/hosts.example.yaml")
for path in candidates:
    if not path or not path.is_file():
        continue
    cfg = yaml.safe_load(path.read_text()) or {}
    for name, host in (cfg.get("hosts") or {}).items():
        plat = str(host.get("platform", "linux") or "linux").strip().lower()
        if plat not in ("linux", "unix", ""):
            print(name)
            raise SystemExit(0)
PY
}

mcp_session_start() {
  local user="${1:-}" role="${2:-}"
  MCP_SESSION_ID=""
  local hf
  local -a hdr=(
    -H "Authorization: $MCP_AUTH"
    -H 'Content-Type: application/json'
    -H 'Accept: application/json, text/event-stream'
  )
  [ -n "$user" ] && hdr+=(-H "X-Auth-User: $user" -H "X-Forwarded-User: $user")
  [ -n "$role" ] && hdr+=(-H "X-Auth-Role: $role")
  hf=$(mktemp)
  curl -sk -m10 -D "$hf" -o /dev/null -X POST "$MCP_URL" "${hdr[@]}" \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"harness","version":"1"}}}' \
    >/dev/null 2>&1 || true
  MCP_SESSION_ID=$(grep -i '^mcp-session-id:' "$hf" | awk '{print $2}' | tr -d '\r')
  rm -f "$hf"
  curl -sk -m10 -o /dev/null -X POST "$MCP_URL" "${hdr[@]}" \
    ${MCP_SESSION_ID:+-H "Mcp-Session-Id: $MCP_SESSION_ID"} \
    -d '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
    >/dev/null 2>&1 || true
}

# mcp_tool_call TOOL JSON_ARGS [USER] [ROLE]  -> last SSE data line
mcp_tool_call() {
  local tool="$1" args="$2" user="${3:-}" role="${4:-}"
  local -a hdr=(
    -H "Authorization: $MCP_AUTH"
    -H 'Content-Type: application/json'
    -H 'Accept: application/json, text/event-stream'
  )
  [ -n "$MCP_SESSION_ID" ] && hdr+=(-H "Mcp-Session-Id: $MCP_SESSION_ID")
  [ -n "$user" ] && hdr+=(-H "X-Auth-User: $user" -H "X-Forwarded-User: $user")
  [ -n "$role" ] && hdr+=(-H "X-Auth-Role: $role")
  curl -sk -m25 -X POST "$MCP_URL" "${hdr[@]}" \
    -d "$(jq -n --arg tool "$tool" --argjson args "$args" \
      '{jsonrpc:"2.0",id:2,method:"tools/call",params:{name:$tool,arguments:$args}}')" \
    2>/dev/null | sed -n 's/^data: //p' | tail -1
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
    # Filtered show may fail on device; RBAC did not trip.
    echo allow
  else
    echo err
  fi
}

mcp_run_command_verdict() {
  local r
  r=$(mcp_tool_call run_command "$(jq -n --arg h "$1" --arg c "$2" '{host:$h,command:$c}')")
  if mcp_response_is_rbac_block "$r" || mcp_response_is_allowlist_block "$r" || echo "$r" | grep -q '"error"'; then
    echo block
  elif echo "$r" | grep -q '"exit_code"'; then
    echo allow
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
