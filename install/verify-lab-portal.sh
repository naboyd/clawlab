#!/usr/bin/env bash
# verify-lab-portal.sh — post-install checks for HTTPS lab portal (:8443 + install-portals)
#
# Usage:
#   bash install/verify-lab-portal.sh
#   bash install/verify-lab-portal.sh --quiet   # summary only on failure
#
# Reads ~/.claw-portals/config.env when present; override with PORT_PORTAL, DOMAIN, etc.
#
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG_FILE="${CLAW_PORTALS_CONFIG:-$HOME/.claw-portals/config.env}"

PASS=0
FAIL=0
QUIET=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --quiet|-q) QUIET=1 ;;
    -h|--help)
      sed -n '1,12p' "$0" | sed 's/^# \{0,1\}//'
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
  python3 - "$1" "${2:-127.0.0.1}" <<'PY'
import socket, sys
host, port = sys.argv[2], int(sys.argv[1])
s = socket.socket(); s.settimeout(0.4)
try:
    s.connect((host, port)); sys.exit(0)
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
}

mcp_proxy_bind() {
  local dropin="$HOME/.config/systemd/user/mcp-identity-proxy.service.d/clawlab.conf"
  local bind=""
  if [[ -f "$dropin" ]]; then
    bind="$(grep -E '^Environment=SSH_OPS_MCP_PROXY_HOST=' "$dropin" 2>/dev/null \
      | head -1 | sed 's/^Environment=SSH_OPS_MCP_PROXY_HOST=//' || true)"
  fi
  printf '%s' "${bind:-${LAN_IP:-127.0.0.1}}"
}

journal_hint() {
  local unit="$1" n="${2:-8}"
  journalctl --user -u "$unit" -n "$n" --no-pager 2>/dev/null | sed 's/^/       /' || true
}

check_port() {
  local label="$1" p="$2" host="${3:-127.0.0.1}"
  if port_open "$p" "$host"; then
    if [[ "$host" == "127.0.0.1" ]]; then
      ok "$label :$p"
    else
      ok "$label :$p on $host"
    fi
  else
    bad "$label :$p on $host"
  fi
}

check_port_either() {
  local label="$1" p="$2" host_a="$3" host_b="$4"
  if port_open "$p" "$host_a"; then
    ok "$label :$p on $host_a"
    return 0
  fi
  if [[ "$host_b" != "$host_a" ]] && port_open "$p" "$host_b"; then
    ok "$label :$p on $host_b (not on $host_a)"
    return 0
  fi
  bad "$label :$p (not on $host_a or $host_b)"
  return 1
}

wait_port_open() {
  local p="$1" host="${2:-127.0.0.1}" tries="${3:-12}"
  local i=0
  while [[ "$i" -lt "$tries" ]]; do
    if port_open "$p" "$host"; then
      return 0
    fi
    sleep 0.5
    i=$((i + 1))
  done
  return 1
}

check_mcp_proxy_port() {
  local label="$1" p="$2"
  local -a hosts=("127.0.0.1")
  if [[ -n "$LAN_IP" && "$LAN_IP" != "127.0.0.1" ]]; then
    hosts+=("$LAN_IP")
  fi
  if [[ -n "$PROXY_BIND" && "$PROXY_BIND" != "127.0.0.1" && "$PROXY_BIND" != "$LAN_IP" ]]; then
    hosts+=("$PROXY_BIND")
  fi
  local h
  for h in "${hosts[@]}"; do
    if port_open "$p" "$h"; then
      ok "$label :$p on $h"
      return 0
    fi
  done
  bad "$label :$p (checked: ${hosts[*]})"
  return 1
}

if [[ -f "$CONFIG_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$CONFIG_FILE"
fi

TLS_MODE="${TLS_MODE:-https-le}"
AUTH_MODE="${AUTH_MODE:-claw-auth}"
DOMAIN="${DOMAIN:-lab.example.com}"
LAN_IP="${LAN_IP:-127.0.0.1}"
PORT_PORTAL="${PORT_PORTAL:-8443}"
SCHEME="${SCHEME:-}"
if [[ -z "$SCHEME" ]]; then
  [[ "$TLS_MODE" == "http" ]] && SCHEME="http" || SCHEME="https"
fi

portal_url="${SCHEME}://${DOMAIN}:${PORT_PORTAL}/"
curl_portal=(curl -fsS -o /dev/null -w '%{http_code}')
[[ "$SCHEME" == "https" ]] && curl_portal+=(-k)

echo "=== lab portal verification (${portal_url}) ==="
echo "  config: ${CONFIG_FILE}"
PROXY_BIND="$(mcp_proxy_bind)"
echo "  mcp proxy bind (dropin): ${PROXY_BIND}:8767 · LAN_IP=${LAN_IP}"
echo

for unit in claw-auth openclaw-gateway mcp-identity-proxy defenseclaw-webgui; do
  if systemctl --user is-active "$unit.service" >/dev/null 2>&1; then
    ok "systemd $unit active"
  else
    bad "systemd $unit not active"
  fi
done

if systemctl is-active nginx >/dev/null 2>&1; then
  ok "nginx active"
else
  bad "nginx not active"
fi

if ls /etc/nginx/sites-enabled/clawlab-*.conf >/dev/null 2>&1; then
  ok "nginx clawlab portal site enabled"
else
  bad "nginx clawlab portal site missing in sites-enabled"
fi

check_port claw-auth 8780
MCP_IDENTITY_EXT="$HOME/.openclaw/extensions/clawlab-mcp-identity/openclaw.plugin.json"
if [[ -f "$MCP_IDENTITY_EXT" ]]; then
  ok "clawlab-mcp-identity extension installed"
else
  bad "clawlab-mcp-identity extension missing ($MCP_IDENTITY_EXT)"
  if [[ "$QUIET" -eq 0 ]]; then
    echo "       fix: bash $REPO/admin-access/configure-openclaw-mcp-identity.sh"
  fi
fi
if wait_port_open 18789 "127.0.0.1" 12; then
  ok "openclaw-gateway :18789"
else
  bad "openclaw-gateway :18789"
  if [[ "$QUIET" -eq 0 ]]; then
    echo "       recent openclaw-gateway journal:"
    journal_hint openclaw-gateway.service 12
    echo "       fix: bash $REPO/admin-access/configure-openclaw-mcp-identity.sh"
    echo "            systemctl --user restart openclaw-gateway"
  fi
fi
check_port ssh-ops-gui 8765
check_port ssh-ops-mcp 8766
if ! check_mcp_proxy_port mcp-identity-proxy 8767; then
  if [[ "$QUIET" -eq 0 ]]; then
    echo "       recent mcp-identity-proxy journal:"
    journal_hint mcp-identity-proxy.service 12
    echo "       fix: bash $REPO/admin-access/configure-portal-mcp-auth.sh"
  fi
fi
check_port defenseclaw-webgui 8770

if command -v podman >/dev/null 2>&1; then
  for name in ssh-ops-gui ssh-ops-mcp; do
    if podman ps --format '{{.Names}}' 2>/dev/null | grep -qx "$name"; then
      ok "podman $name running"
    else
      bad "podman $name not running"
    fi
  done
else
  warn "podman not on PATH"
fi

curl -fsS "http://127.0.0.1:8780/healthz" >/dev/null 2>&1 && ok "claw-auth /healthz" || bad "claw-auth /healthz"

verify_code="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8780/verify 2>/dev/null || echo 000)"
if [[ "$verify_code" == "401" ]]; then
  ok "claw-auth /verify -> HTTP 401 (no session)"
else
  bad "claw-auth /verify -> HTTP $verify_code (expect 401 without cookie)"
fi

hub_code="$("${curl_portal[@]}" "$portal_url" 2>/dev/null || echo 000)"
if [[ "$hub_code" == "200" || "$hub_code" =~ ^30 ]]; then
  ok "portal hub $portal_url (HTTP $hub_code)"
else
  bad "portal hub $portal_url (HTTP $hub_code)"
fi

ssh_ops_code="$("${curl_portal[@]}" "${SCHEME}://${DOMAIN}:${PORT_PORTAL}/ssh-ops/" 2>/dev/null || echo 000)"
if [[ "$ssh_ops_code" == "401" || "$ssh_ops_code" == "403" || "$ssh_ops_code" =~ ^30 ]]; then
  ok "portal /ssh-ops/ without session (HTTP $ssh_ops_code — auth gate expected)"
else
  bad "portal /ssh-ops/ without session (HTTP $ssh_ops_code)"
fi

direct_gui_code="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8765/ 2>/dev/null || echo 000)"
if [[ "$direct_gui_code" == "403" ]]; then
  ok "ssh-ops GUI direct :8765 -> HTTP 403 (CLAW_AUTH_REQUIRED)"
elif [[ "$direct_gui_code" == "200" ]]; then
  warn "ssh-ops GUI direct :8765 -> HTTP 200 (CLAW_AUTH_REQUIRED may be off)"
  ok "ssh-ops GUI direct :8765 listening"
else
  bad "ssh-ops GUI direct :8765 (HTTP $direct_gui_code)"
fi

if [[ -f "$REPO/ssh-ops-mcp/scripts/ios-config-drift-check.py" ]]; then
  ok "ios-config-drift-check.py present"
else
  bad "ios-config-drift-check.py missing"
fi

if systemctl --user is-active ios-config-archive.timer >/dev/null 2>&1 \
  || [[ -f "$HOME/Library/LaunchAgents/com.clawlab.ios-config-archive.plist" ]]; then
  ok "ios-config-archive scheduler present"
else
  warn "ios-config-archive timer not active — bash admin-access/install-clawlab-extras.sh"
fi

VENV="${CLAWLAB_VENV:-$HOME/.clawlab/venv}"
PY="${CLAW_PYTHON:-$VENV/bin/python}"
if [[ -x "$PY" ]]; then
  count="$("$PY" -c "import sys; sys.path.insert(0, '$REPO/claw-auth'); import store; store.init_db(); print(store.user_count())" 2>/dev/null || echo 0)"
  if [[ "${count:-0}" -gt 0 ]]; then
    ok "claw-auth users: $count"
  else
    warn "no claw-auth users — create: $PY $REPO/claw-auth/manage.py create-user admin"
  fi
else
  warn "venv python missing at $PY"
fi

echo
if [[ "$FAIL" -eq 0 ]]; then
  echo "Lab portal checks passed ($PASS ok)."
  exit 0
fi
echo "$FAIL check(s) failed, $PASS ok."
if [[ "$QUIET" -eq 0 ]]; then
  echo "Logs: journalctl --user -u claw-auth -n 30 · podman logs ssh-ops-mcp · ${CLAWLAB_RUN:-$HOME/.clawlab/run}/install.log"
fi
exit 1
