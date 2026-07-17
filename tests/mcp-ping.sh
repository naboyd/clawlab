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
  printf '  raw response (first 400 chars): %s\n' "$(printf '%s' "$r" | head -c 400)"
  fail "list_hosts parsed zero hosts"
fi

step "5) Linux host probe (optional)"
linux="$(mcp_pick_linux_host "${CLAWLAB_HOST:-}" || true)"
if [ -n "$linux" ]; then
  ok "reachable linux host: $linux"
else
  warn "no reachable linux host (Mac: enable Remote Login for mac-local)"
fi

step "6) Network host (optional)"
net="$(mcp_pick_network_host "${CLAWLAB_SWITCH:-}" || true)"
if [ -n "$net" ]; then
  ok "network host in inventory: $net"
else
  warn "no network host in inventory (sections 2b/2c will skip)"
fi

printf '\nMCP ping complete.\n'
