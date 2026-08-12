#!/usr/bin/env bash
# Scenario: operator Alice blocked from full show running-config (MCP RBAC).
# Verifies verified identity headers override honor-based requested_by.
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"

REPO="$(cd "$(dirname "$0")/.." && pwd)"
. "$REPO/tests/lib-mcp-harness.sh"

OPERATOR="${RBAC_OPERATOR_USER:-alice}"
ADMIN_USER="${RBAC_ADMIN_USER:-admin}"
NET_HOST="${CLAWLAB_SWITCH:-}"
LINUX_HOST="${CLAWLAB_HOST:-lab-host}"
MCP_AUTH=""
MCP_URL=""
RUN_LIVE=1
[ "${1:-}" = "--local-only" ] && RUN_LIVE=0

PASS=0
FAIL=0
hdr(){ printf '\n=== %s ===\n' "$1"; }
chk(){
  if [ "$2" = "$3" ]; then
    PASS=$((PASS + 1))
    printf '  [PASS] %-55s expect=%-5s got=%s\n' "$1" "$2" "$3"
  else
    FAIL=$((FAIL + 1))
    printf '  [FAIL] %-55s expect=%-5s got=%s\n' "$1" "$2" "$3"
  fi
}

MCP_AUTH=$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.openclaw/openclaw.json')))['mcp']['servers']['ssh-ops']['headers']['Authorization'])" 2>/dev/null) || true
MCP_URL=$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.openclaw/openclaw.json')))['mcp']['servers']['ssh-ops']['url'])" 2>/dev/null) || true
[ -z "$NET_HOST" ] && NET_HOST=$(mcp_discover_net_host || true)

hdr "Scenario: operator blocked from show running-config (MCP RBAC)"
echo "  Operator user: $OPERATOR | Admin user: $ADMIN_USER"
echo "  Network host:  ${NET_HOST:-<none>} | Linux host: $LINUX_HOST"
echo "  MCP URL:       ${MCP_URL:-<none>}"

hdr "1) Local RBAC policy module (offline)"
if python3 "$REPO/tests/test_rbac.py" -q 2>/dev/null; then
  chk "test_rbac.py unit suite" ok ok
else
  chk "test_rbac.py unit suite" ok fail
fi

if [ "$RUN_LIVE" = 0 ] || [ -z "$MCP_AUTH" ] || [ -z "$MCP_URL" ]; then
  hdr "2) Live MCP RBAC probes skipped"
  echo "  Use without --local-only when openclaw.json has ssh-ops MCP auth/url."
  hdr "Result"
  echo "  PASS=$PASS  FAIL=$FAIL"
  exit "$FAIL"
fi

mcp_session_start

hdr "2) Operator identity — sensitive reads blocked"
if [ -n "$NET_HOST" ]; then
  chk "OUT: operator show running-config" block \
    "$(mcp_rbac_verdict "$OPERATOR" operator "$NET_HOST" "show running-config")"
  chk "IN:  operator show run | include interface" allow \
    "$(mcp_rbac_verdict "$OPERATOR" operator "$NET_HOST" "show run | include interface")"
  chk "IN:  operator show version" allow \
    "$(mcp_rbac_verdict "$OPERATOR" operator "$NET_HOST" "show version")"
else
  echo "  SKIP: no network host in hosts.yaml (set CLAWLAB_SWITCH)"
fi

chk "OUT: operator cat /etc/shadow on Linux" block \
  "$(mcp_rbac_verdict "$OPERATOR" operator "$LINUX_HOST" "cat /etc/shadow")"

RESP_DL=$(mcp_tool_call download_file \
  "$(jq -n --arg h "$LINUX_HOST" '{host:$h,remote_path:"/etc/hostname",local_name:"harness-rbac-dl.txt"}')" \
  "$OPERATOR" operator)
if mcp_response_is_rbac_block "$RESP_DL"; then
  chk "OUT: operator download_file" block block
else
  chk "OUT: operator download_file" block allow
fi

hdr "3) Admin identity — full config allowed (RBAC does not block)"
if [ -n "$NET_HOST" ]; then
  RESP_ADMIN=$(mcp_tool_call run_command \
    "$(jq -n --arg h "$NET_HOST" --arg c "show running-config" '{host:$h,command:$c}')" \
    "$ADMIN_USER" admin)
  if mcp_response_is_rbac_block "$RESP_ADMIN"; then
    chk "IN: admin show running-config (no RBAC deny)" allow block
  else
    chk "IN: admin show running-config (no RBAC deny)" allow allow
  fi
else
  echo "  SKIP: no network host for admin show running-config"
fi

hdr "4) Identity spoof — requested_by must match verified header"
RESP_SPOOF=$(mcp_tool_call propose_change "$(jq -n \
  --arg h "${NET_HOST:-$LINUX_HOST}" \
  '{host:$h,change_type:"ios_config_lines",requested_by:"bob",intent:"harness spoof",
    spec:{group:"vlan_l3",lines:["vlan 99"," name HARNESS-RBAC"]}}')" \
  "$OPERATOR" operator)
if echo "$RESP_SPOOF" | grep -qiE 'identity_mismatch|does not match verified user'; then
  chk "OUT: requested_by bob with header alice" block block
else
  chk "OUT: requested_by bob with header alice" block allow
  echo "  Response: $(echo "$RESP_SPOOF" | head -c 300)"
fi

RESP_OK=$(mcp_tool_call propose_change "$(jq -n \
  --arg h "${NET_HOST:-$LINUX_HOST}" \
  --arg u "$OPERATOR" \
  '{host:$h,change_type:"ios_config_lines",requested_by:$u,intent:"harness ok",
    spec:{group:"vlan_l3",lines:["vlan 98"," name HARNESS-RBAC-OK"]}}')" \
  "$OPERATOR" operator)
if mcp_response_is_rbac_block "$RESP_OK"; then
  chk "IN: requested_by matches verified operator" allow block
elif echo "$RESP_OK" | grep -qiE 'identity_mismatch'; then
  chk "IN: requested_by matches verified operator" allow block
elif echo "$RESP_OK" | grep -qE 'change_id|proposed|error'; then
  chk "IN: requested_by matches verified operator" allow allow
else
  chk "IN: requested_by matches verified operator" allow err
fi

hdr "5) Anonymous bearer — no verified identity on propose"
RESP_ANON=$(mcp_tool_call propose_change "$(jq -n \
  --arg h "${NET_HOST:-$LINUX_HOST}" \
  '{host:$h,change_type:"ios_config_lines",requested_by:"alice",intent:"harness anon",
    spec:{group:"vlan_l3",lines:["vlan 97"," name HARNESS-ANON"]}}')")
if mcp_response_is_rbac_block "$RESP_ANON"; then
  chk "OUT: propose without X-Auth-User (honor-based blocked)" block block
else
  chk "OUT: propose without X-Auth-User (honor-based blocked)" block allow
  echo "  WARN: RBAC may be off or requested_by still trusted without headers"
fi

hdr "Result"
echo "  PASS=$PASS  FAIL=$FAIL"
[ "$FAIL" -eq 0 ] && echo "  Scenario OK — operator cannot dump full running-config without admin role."
exit "$FAIL"
