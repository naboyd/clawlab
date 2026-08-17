#!/usr/bin/env bash
# verify-local-full.sh — post-install checks for macOS/Linux local-full stack
#
# Usage:
#   bash install/verify-local-full.sh
#   bash install/verify-local-full.sh --mcp-ping   # also run tests/mcp-ping.sh
#
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=lib/clawlab-local-full.sh
source "$SCRIPT_DIR/lib/clawlab-local-full.sh"

PORT="${LOCAL_FULL_PORT:-8083}"
MCP_PING=0
PASS=0
FAIL=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mcp-ping) MCP_PING=1 ;;
    -h|--help)
      sed -n '1,7p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
  shift
done
warn() { printf 'WARN: %s\n' "$*" >&2; }
ok() { printf '  OK   %s\n' "$*"; PASS=$((PASS + 1)); }
bad() { printf '  FAIL %s\n' "$*"; FAIL=$((FAIL + 1)); }

port_open() {
  python3 - "$1" <<'PY'
import socket, sys
s = socket.socket(); s.settimeout(0.4)
try:
    s.connect(("127.0.0.1", int(sys.argv[1]))); sys.exit(0)
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
}

echo "=== local-full verification (:${PORT}) ==="
echo

bash "$SCRIPT_DIR/local-full-ctl.sh" status || true
echo

check_port() {
  local label="$1" p="$2"
  if port_open "$p"; then ok "$label :$p"; else bad "$label :$p"; fi
}

check_port claw-auth 8780
check_port defenseclaw-webgui 8770
check_port openclaw-gateway 18789
check_port ssh-ops-gui 8765
check_port ssh-ops-mcp 8766
check_port mcp-identity-proxy 8767
check_port defenseclaw-sidecar 18970
check_port portal-nginx "$PORT"

if clawlab_local_full_sidecar_ok; then
  ok "DefenseClaw sidecar :18970 listening"
else
  bad "DefenseClaw sidecar :18970 not listening (defenseclaw-gateway restart)"
fi

if clawlab_local_full_guardrails_ok; then
  ok "DefenseClaw revshell + user CRUD rules blocking"
else
  bad "DefenseClaw revshell rules not blocking (install-clawlab-guardrail-rules.sh + gateway restart)"
fi

curl -fsS "http://127.0.0.1:8780/healthz" >/dev/null 2>&1 && ok "claw-auth /healthz" || bad "claw-auth /healthz"

code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}/" 2>/dev/null || echo 000)"
if [[ "$code" == "200" || "$code" =~ ^30 ]]; then
  ok "portal / (HTTP $code)"
else
  bad "portal / (HTTP $code)"
fi

if [[ -f "$HOME/.openclaw/openclaw.json" ]]; then
  python3 - <<'PY' && ok "openclaw.json token SecretRef" || bad "openclaw.json token SecretRef"
import json, sys
from pathlib import Path
d = json.loads(Path.home().joinpath(".openclaw/openclaw.json").read_text())
tok = d.get("gateway", {}).get("auth", {}).get("token", "")
sys.exit(0 if tok == "${OPENCLAW_GATEWAY_TOKEN}" else 1)
PY
else
  bad "missing ~/.openclaw/openclaw.json"
fi

if [[ -f "$CLAWLAB_NGINX/clawlab-portal.conf" ]]; then
  if grep -q 'upstream_http_x_auth_user' "$CLAWLAB_NGINX/clawlab-portal.conf"; then
    ok "nginx auth_request_set uses x_auth_user"
  else
    bad "nginx auth_request_set (wrong upstream header var?)"
  fi
else
  bad "missing $CLAWLAB_NGINX/clawlab-portal.conf"
fi

if [[ -x "$REPO/claw-auth/manage.py" || -f "$REPO/claw-auth/manage.py" ]]; then
  count="$("$HOME/.clawlab/venv/bin/python" -c "import sys; sys.path.insert(0, '$REPO/claw-auth'); import store; store.init_db(); print(store.user_count())" 2>/dev/null || echo 0)"
  if [[ "${count:-0}" -gt 0 ]]; then ok "claw-auth users: $count"; else warn "no claw-auth users — create: ~/.clawlab/venv/bin/python $REPO/claw-auth/manage.py create-user admin"; fi
fi

echo
echo "--- OpenClaw device pairing (gateway) ---"
if port_open 18789; then
  if [[ -f "$REPO/claw-auth/openclaw_devices.py" ]]; then
    "$HOME/.clawlab/venv/bin/python" - <<PY 2>/dev/null | sed 's/^/    /' || warn "device list via gateway API failed"
import sys
sys.path.insert(0, "$REPO/claw-auth")
import openclaw_devices as od
data = od.list_devices()
pending = data.get("pending") or []
paired = data.get("paired") or []
print(f"source={data.get('source')} pending={len(pending)} paired={len(paired)}")
for row in pending[:5]:
    rid = row.get("requestId") or row.get("id") or "?"
    print(f"  pending: {rid}")
PY
    ok "gateway :18789 reachable for device pairing"
  else
    ok "gateway :18789 (device API module missing)"
  fi
elif command -v openclaw >/dev/null 2>&1; then
  openclaw devices list 2>/dev/null | sed 's/^/    /' || warn "openclaw devices list failed (gateway down?)"
  warn "openclaw-gateway :18789 not listening — see ~/.clawlab/run/openclaw-gateway.log (often obsolete gateway.host key)"
else
  warn "openclaw-gateway :18789 not listening — see ~/.clawlab/run/openclaw-gateway.log"
fi

echo
if clawlab_local_full_supported; then
  if clawlab_local_full_doctor "$REPO"; then
    ok "local-full doctor"
  else
    bad "local-full doctor (fix items above)"
  fi
fi

if [[ -f "$REPO/ssh-ops-mcp/scripts/ios-config-drift-check.py" ]]; then
  ok "ios-config-drift-check.py present"
else
  bad "ios-config-drift-check.py missing (update clawlab repo)"
fi

if [[ -L "$HOME/.openclaw/workspace/skills/ios-config-drift" ]] \
  || [[ -d "$HOME/.openclaw/workspace/skills/ios-config-drift" ]]; then
  ok "ios-config-drift skill linked in OpenClaw workspace"
else
  warn "ios-config-drift skill not linked — bash admin-access/install-clawlab-skills.sh"
fi

if [[ "$MCP_PING" -eq 1 && -x "$REPO/tests/mcp-ping.sh" ]]; then
  echo
  echo "--- mcp-ping ---"
  if bash "$REPO/tests/mcp-ping.sh"; then
    ok "mcp-ping"
  else
    bad "mcp-ping (see output above)"
  fi
fi

echo
if [[ "$FAIL" -eq 0 ]]; then
  echo "All required checks passed ($PASS ok)."
  exit 0
fi
echo "$FAIL check(s) failed, $PASS ok — see install/local-full-ctl.sh restart"
exit 1
