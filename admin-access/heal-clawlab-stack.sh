#!/usr/bin/env bash
# Verify and repair common clawlab lab stack breakages.
#
# Catches issues that cause 502s, MCP drift failures, and gateway CONFIG errors:
#   - incomplete defenseclaw OpenClaw extension (missing dist/index.js)
#   - stale ssh-ops-mcp quadlet (example IP / wrong TLS cert names)
#   - stopped user services (gateway, MCP, identity proxy, claw-auth)
#
# Usage:
#   bash admin-access/heal-clawlab-stack.sh           # report only
#   bash admin-access/heal-clawlab-stack.sh --fix     # repair + restart failed units
#   bash admin-access/heal-clawlab-stack.sh --fix --quiet
set -Eeuo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib/ensure-openclaw-extensions.sh
source "$REPO/admin-access/lib/ensure-openclaw-extensions.sh"

PORTAL_ENV="${CLAW_PORTAL_ENV:-$HOME/.claw-portals/config.env}"
FIX=0
QUIET=0
ISSUES=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --fix) FIX=1 ;;
    --quiet|-q) QUIET=1 ;;
    -h|--help)
      sed -n '1,14p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
  shift
done

say() { [[ "$QUIET" -eq 1 ]] || printf '>> %s\n' "$*"; }
warn_issue() { printf 'ISSUE: %s\n' "$*" >&2; ISSUES=$((ISSUES + 1)); }
ok() { [[ "$QUIET" -eq 1 ]] || printf 'OK:   %s\n' "$*"; }

if [[ -f "$PORTAL_ENV" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$PORTAL_ENV"
  set +a
fi

export CLAWLAB_REPO="$REPO"
OPENCLAW_BIN="${OPENCLAW_BIN:-$HOME/.local/bin/openclaw}"
if [[ ! -x "$OPENCLAW_BIN" ]] && command -v openclaw >/dev/null 2>&1; then
  OPENCLAW_BIN="$(command -v openclaw)"
fi

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

unit_active() {
  systemctl --user is-active --quiet "$1" 2>/dev/null
}

restart_unit() {
  local unit="$1"
  systemctl --user reset-failed "$unit" 2>/dev/null || true
  systemctl --user restart "$unit" 2>/dev/null || return 1
}

check_extensions() {
  local dc_index="${HOME}/.openclaw/extensions/defenseclaw/dist/index.js"
  local mcp_id="${HOME}/.openclaw/extensions/clawlab-mcp-identity/openclaw.plugin.json"

  if [[ ! -f "$dc_index" ]]; then
    warn_issue "defenseclaw OpenClaw extension incomplete (missing dist/index.js)"
    if [[ "$FIX" -eq 1 ]]; then
      ensure_defenseclaw_openclaw_extension || return 1
      ok "defenseclaw extension restored"
    fi
  else
    ok "defenseclaw extension present"
  fi

  if [[ ! -f "$mcp_id" ]]; then
    warn_issue "clawlab-mcp-identity extension missing"
    if [[ "$FIX" -eq 1 ]]; then
      ensure_clawlab_mcp_identity_extension || true
    fi
  else
    ok "clawlab-mcp-identity extension present"
  fi

  if [[ "$FIX" -eq 1 ]]; then
    install_openclaw_ext_heal_units
    ok "openclaw-ext-heal watcher enabled"
  fi
}

check_mcp_quadlet() {
  local quadlet="${HOME}/.config/containers/systemd/ssh-ops-mcp.container"
  [[ -f "$quadlet" ]] || {
    if command -v podman >/dev/null 2>&1 && [[ -f "$PORTAL_ENV" ]]; then
      warn_issue "ssh-ops-mcp quadlet not installed"
      [[ "$FIX" -eq 1 ]] && bash "$REPO/admin-access/install-ssh-ops-mcp-quadlet.sh" && ok "ssh-ops-mcp quadlet installed"
    fi
    return 0
  }

  local pub tls_cert
  pub="$(grep -E '^PublishPort=' "$quadlet" 2>/dev/null | head -1 | cut -d= -f2- || true)"
  tls_cert="$(grep -E '^Environment=SSH_OPS_MCP_TLS_CERT=' "$quadlet" 2>/dev/null | head -1 | cut -d= -f2- || true)"

  if [[ "$pub" == *"192.168.1.10"* && "${LAN_IP:-}" != "192.168.1.10" ]]; then
    warn_issue "ssh-ops-mcp quadlet uses example IP in PublishPort ($pub)"
    [[ "$FIX" -eq 1 ]] && bash "$REPO/admin-access/install-ssh-ops-mcp-quadlet.sh" && ok "ssh-ops-mcp quadlet refreshed"
  elif [[ "$pub" == *"@MCP_PUBLISH@"* ]]; then
    warn_issue "ssh-ops-mcp quadlet not rendered (placeholder PublishPort)"
    [[ "$FIX" -eq 1 ]] && bash "$REPO/admin-access/install-ssh-ops-mcp-quadlet.sh" && ok "ssh-ops-mcp quadlet rendered"
  elif [[ -n "$pub" ]]; then
    ok "ssh-ops-mcp quadlet PublishPort=$pub"
  fi

  if [[ -n "${DOMAIN:-}" && -n "$tls_cert" && "$tls_cert" != *"/certs/${DOMAIN}."* ]]; then
    warn_issue "ssh-ops-mcp TLS cert path does not match DOMAIN=$DOMAIN"
    [[ "$FIX" -eq 1 ]] && bash "$REPO/admin-access/install-ssh-ops-mcp-quadlet.sh" && ok "ssh-ops-mcp TLS paths updated"
  fi
}

check_openclaw_config() {
  [[ -x "$OPENCLAW_BIN" ]] || {
    warn_issue "openclaw CLI not found ($OPENCLAW_BIN)"
    return 0
  }
  if ! "$OPENCLAW_BIN" config validate >/dev/null 2>&1; then
    warn_issue "openclaw.json invalid (run: openclaw doctor --fix)"
    return 0
  fi
  ok "openclaw.json validates"
}

check_services() {
  local -a units=(claw-auth.service openclaw-gateway.service)
  if [[ -f "$PORTAL_ENV" ]] && command -v podman >/dev/null 2>&1; then
    units+=(ssh-ops-mcp.service mcp-identity-proxy.service)
  fi

  local unit
  for unit in "${units[@]}"; do
    if unit_active "$unit"; then
      ok "$unit active"
      continue
    fi
    warn_issue "$unit not active"
    if [[ "$FIX" -eq 1 ]]; then
      if [[ "$unit" == "openclaw-gateway.service" ]]; then
        ensure_openclaw_extensions || true
      fi
      if restart_unit "$unit"; then
        sleep 2
        if unit_active "$unit"; then
          ok "$unit restarted"
        else
          warn_issue "$unit still not active after restart"
        fi
      else
        warn_issue "failed to restart $unit"
      fi
    fi
  done
}

check_ports() {
  port_open 8780 && ok "claw-auth :8780" || warn_issue "claw-auth :8780 not listening"
  if port_open 18789; then
    ok "openclaw-gateway :18789"
  else
    warn_issue "openclaw-gateway :18789 not listening (portal /openclaw/ → 502)"
  fi
  if [[ -f "$PORTAL_ENV" ]]; then
    port_open 8766 && ok "ssh-ops MCP :8766" || warn_issue "ssh-ops MCP :8766 not listening"
    local bind="${LAN_IP:-127.0.0.1}"
    if port_open 8767 "$bind" || port_open 8767 127.0.0.1; then
      ok "MCP identity proxy :8767"
    else
      warn_issue "MCP identity proxy :8767 not listening"
    fi
  fi
}

say "ClawLab stack heal (mode=$([[ "$FIX" -eq 1 ]] && echo fix || echo check))"
check_extensions
check_mcp_quadlet
check_openclaw_config
if [[ "$FIX" -eq 1 ]]; then
  check_services
fi
check_ports
if [[ "$FIX" -eq 1 ]] && ! unit_active openclaw-gateway.service; then
  check_services
fi

if [[ "$ISSUES" -gt 0 ]]; then
  if [[ "$FIX" -eq 0 ]]; then
    say "Run with --fix to repair: bash $REPO/admin-access/heal-clawlab-stack.sh --fix"
  fi
  exit 1
fi

say "Stack checks passed"
exit 0
