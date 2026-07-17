#!/usr/bin/env bash
# Step-by-step MCP connectivity diagnostic for local-full testers.
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"

REPO="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib-mcp-harness.sh
source "$REPO/tests/lib-mcp-harness.sh"

step() { printf '\n== %s ==\n' "$1"; }
ok() { printf '  OK: %s\n' "$1"; }
fail() { printf '  FAIL: %s\n' "$1"; exit 1; }
warn() { printf '  WARN: %s\n' "$1"; }

printf 'clawlab tests @ %s\n' "$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo unknown)"
step "1) Config"
mcp_load_config
[ -n "${MCP_URL:-}" ] || fail "MCP_URL empty (openclaw.json missing ssh-ops entry?)"
[ -n "${MCP_AUTH:-}" ] || fail "MCP auth empty (ssh-ops secrets or openclaw.json)"
ok "MCP_URL=$MCP_URL"
ok "Authorization=${MCP_AUTH:0:20}..."

step "2) TCP reachability"
code="$(curl -sS -m5 -o /dev/null -w '%{http_code}' -X POST "$MCP_URL" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"ping","version":"1"}}}' \
  2>/dev/null || echo 000)"
if [ "$code" = "000" ]; then
  fail "cannot connect to $MCP_URL (is ssh-ops MCP up? bash install/local-full-ctl.sh status)"
fi
ok "HTTP $code on POST initialize (401 without auth is OK)"

step "3) Authenticated initialize + session"
if ! mcp_session_start; then
  fail "${MCP_LAST_ERR:-MCP session init failed}"
fi
ok "Mcp-Session-Id=${MCP_SESSION_ID:0:12}..."

step "4) list_hosts"
r="$(mcp_tool_call list_hosts '{}' || true)"
[ -n "$r" ] || fail "${MCP_LAST_ERR:-list_hosts returned empty body}"
rows="$(mcp_list_hosts_rows "$r" || true)"
if [ -n "$rows" ]; then
  echo "$rows" | while IFS=$'\t' read -r name kind; do
    printf '  host %-24s kind=%s\n' "$name" "$kind"
  done
else
  printf '  raw response (first 500 chars):\n    %s\n' "$(printf '%s' "$r" | head -c 500)"
  if printf '%s' "$r" | python3 -m json.tool >/dev/null 2>&1; then
    printf '  parsed json keys: '
    MCP_JSON="$r" python3 -c 'import json,os; d=json.loads(os.environ["MCP_JSON"]); r=d.get("result"); print(list(r.keys()) if isinstance(r,dict) else type(r).__name__)' 2>/dev/null || true
    echo
  fi
  fail "list_hosts parsed zero hosts (git pull clawlab; need commit a4ea919+)"
fi

step "5) Linux host probe (optional)"
hosts_file="${SSH_OPS_DATA:-$HOME/.clawlab/ssh-ops/data}/hosts.yaml"
if [ -f "$hosts_file" ]; then
  mac_meta="$(python3 -c "
import yaml
from pathlib import Path
p=Path('$hosts_file')
h=(yaml.safe_load(p.read_text()) or {}).get('hosts', {}).get('mac-local', {})
print(h.get('hostname','?'), h.get('username','?'), h.get('key_path','(default keys)'))
" 2>/dev/null || true)"
  [ -n "$mac_meta" ] && ok "mac-local inventory: $mac_meta"
fi
linux="$(mcp_pick_linux_host "${CLAWLAB_HOST:-mac-local}" || true)"
if [ -n "$linux" ]; then
  ok "reachable linux host: $linux"
else
  warn "no reachable linux host from MCP Podman container"
  mcp_session_start >/dev/null 2>&1 || true
  probe="$(mcp_tool_call run_command "$(jq -n --arg h mac-local --arg c true '{host:$h,command:$c}')" 2>/dev/null || true)"
  if [ -n "$probe" ]; then
    payload="$(mcp_tool_payload_json "$probe" 2>/dev/null || true)"
    err="$(MCP_JSON="${payload:-$probe}" python3 -c 'import json,os
raw=os.environ.get("MCP_JSON","")
try: d=json.loads(raw)
except: raise SystemExit(0)
if isinstance(d,dict):
  print(d.get("stderr") or d.get("error") or "")
' 2>/dev/null || true)"
    [ -n "$err" ] && printf '  SSH error: %s\n' "$(printf '%s' "$err" | head -c 240)"
  fi
  if command -v podman >/dev/null 2>&1 && podman container exists ssh-ops-mcp 2>/dev/null; then
    pod_err="$(podman exec ssh-ops-mcp ssh -o BatchMode=yes -o ConnectTimeout=4 \
      -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
      -i /root/.ssh/id_ed25519 "${USER}@host.containers.internal" true 2>&1 || true)"
    if [ -z "$pod_err" ]; then
      ok "Podman direct SSH to Mac OK"
    else
      printf '  podman ssh: %s\n' "$(printf '%s' "$pod_err" | head -1)"
      warn "run: bash install/local-full-ctl.sh restart  (authorized_keys + mac-local key_path)"
    fi
  fi
fi

step "6) Network host (optional)"
net="$(mcp_pick_network_host "${CLAWLAB_SWITCH:-}" || true)"
if [ -n "$net" ]; then
  ok "network host in inventory: $net"
else
  warn "no network host in inventory (sections 2b/2c will skip)"
fi

printf '\nMCP ping complete.\n'
