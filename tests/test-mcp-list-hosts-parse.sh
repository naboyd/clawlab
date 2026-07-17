#!/usr/bin/env bash
# Offline unit checks for mcp_list_hosts_rows (no live MCP required).
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib-mcp-harness.sh
source "$REPO/tests/lib-mcp-harness.sh"

PASS=0
FAIL=0
check() {
  local name="$1" payload="$2" expect="$3"
  local got
  got="$(MCP_JSON="$payload" mcp_list_hosts_rows "$payload" 2>/dev/null | sort | tr '\n' ';' || true)"
  if [[ "$got" == "$expect" ]]; then
    PASS=$((PASS + 1))
    printf '[PASS] %s\n' "$name"
  else
    FAIL=$((FAIL + 1))
    printf '[FAIL] %s\n  expect: %s\n  got:    %s\n' "$name" "$expect" "$got"
  fi
}

payload_content='{"jsonrpc":"2.0","id":2,"result":{"content":[{"type":"text","text":"[{\"name\":\"mac-local\",\"kind\":\"linux\"}]"}]}}'
payload_sc_list='{"jsonrpc":"2.0","id":2,"result":{"structuredContent":[{"name":"sw1","kind":"network"}]}}'
payload_sc_wrap='{"jsonrpc":"2.0","id":2,"result":{"structuredContent":{"result":[{"name":"n1","kind":"linux"}]}}}'
payload_result_list='{"jsonrpc":"2.0","id":2,"result":[{"name":"r1","kind":"linux"}]}'

check "content.text array" "$payload_content" "mac-local	linux;"
check "structuredContent list" "$payload_sc_list" "sw1	network;"
check "structuredContent.result wrap" "$payload_sc_wrap" "n1	linux;"
check "result list" "$payload_result_list" "r1	linux;"

printf '\nPASS=%s FAIL=%s\n' "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]]
