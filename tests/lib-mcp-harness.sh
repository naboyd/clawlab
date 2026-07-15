#!/usr/bin/env bash
# Shared MCP harness helpers for clawlab test scripts.
# Source from policy-test.sh / scenario-*.sh — do not execute directly.
set -uo pipefail

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
  MCP_SESSION_ID=""
  local hf
  hf=$(mktemp)
  curl -sk -m10 -D "$hf" -o /dev/null -X POST "$MCP_URL" \
    -H "Authorization: $MCP_AUTH" \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"harness","version":"1"}}}' \
    >/dev/null 2>&1 || true
  MCP_SESSION_ID=$(grep -i '^mcp-session-id:' "$hf" | awk '{print $2}' | tr -d '\r')
  rm -f "$hf"
  curl -sk -m10 -o /dev/null -X POST "$MCP_URL" \
    -H "Authorization: $MCP_AUTH" \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' \
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
