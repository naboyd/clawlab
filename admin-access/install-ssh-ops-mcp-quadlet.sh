#!/usr/bin/env bash
# Render and install ssh-ops-mcp Podman quadlet from portal config.
#
# Substitutes PublishPort, data volume, and lego TLS paths from
# ~/.claw-portals/config.env so installs do not keep example values
# (192.168.1.10, lab.example.com).
#
#   bash admin-access/install-ssh-ops-mcp-quadlet.sh
#   bash admin-access/install-ssh-ops-mcp-quadlet.sh --no-restart
set -Eeuo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PORTAL_ENV="${CLAW_PORTAL_ENV:-$HOME/.claw-portals/config.env}"
TEMPLATE="$REPO/quadlets/ssh-ops-mcp.container"
OUT="${SSH_OPS_MCP_QUADLET:-$HOME/.config/containers/systemd/ssh-ops-mcp.container}"
NO_RESTART=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-restart) NO_RESTART=1 ;;
    -h|--help)
      sed -n '1,12p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
  shift
done

say() { printf '>> %s\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*" >&2; }

if [[ -f "$PORTAL_ENV" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$PORTAL_ENV"
  set +a
fi

DOMAIN="${DOMAIN:-}"
LAN_IP="${LAN_IP:-127.0.0.1}"
SSH_OPS_DATA="${SSH_OPS_DATA:-$HOME/.clawlab/ssh-ops/data}"
LEGACY_DATA="${SSH_OPS_LEGACY_DATA:-$HOME/ssh_ops_mcp/data}"

[[ -f "$TEMPLATE" ]] || {
  echo "error: missing $TEMPLATE" >&2
  exit 1
}

_resolve_mcp_publish() {
  if [[ -n "${SSH_OPS_MCP_PUBLISH:-}" ]]; then
    printf '%s' "$SSH_OPS_MCP_PUBLISH"
    return
  fi
  # Raw MCP is internal; external clients use the identity proxy on :8767.
  printf '%s' "127.0.0.1:8766:8766"
}

_resolve_data_rel() {
  if [[ -f "$SSH_OPS_DATA/hosts.yaml" ]]; then
    printf '%s' ".clawlab/ssh-ops/data"
    return
  fi
  if [[ -f "$LEGACY_DATA/hosts.yaml" ]]; then
    warn "hosts.yaml only in legacy $LEGACY_DATA — quadlet will mount legacy path (migrate to ~/.clawlab/ssh-ops/data)"
    printf '%s' "ssh_ops_mcp/data"
    return
  fi
  printf '%s' ".clawlab/ssh-ops/data"
}

_resolve_tls_block() {
  local domain="$1"
  local lego="${SSH_OPS_MCP_TLS_DIR:-$HOME/mcp/acme/lego/certificates}"
  local cert="${SSH_OPS_MCP_TLS_CERT:-}"
  local key="${SSH_OPS_MCP_TLS_KEY:-}"

  if [[ -z "$cert" || -z "$key" ]]; then
    if [[ -n "$domain" && -f "$lego/${domain}.crt" && -f "$lego/${domain}.key" ]]; then
      cert="/certs/${domain}.crt"
      key="/certs/${domain}.key"
    fi
  else
    # Host paths passed explicitly — map into container mount when under lego dir.
    if [[ "$cert" == "$lego/"* ]]; then
      cert="/certs/${cert#"$lego/"}"
    fi
    if [[ "$key" == "$lego/"* ]]; then
      key="/certs/${key#"$lego/"}"
    fi
  fi

  if [[ -n "$cert" && -n "$key" ]]; then
    printf '%s\n' \
      "Volume=%h/mcp/acme/lego/certificates:/certs:ro,Z" \
      "Environment=SSH_OPS_MCP_TLS_CERT=${cert}" \
      "Environment=SSH_OPS_MCP_TLS_KEY=${key}"
    return 0
  fi
  return 1
}

publish="$(_resolve_mcp_publish)"
data_rel="$(_resolve_data_rel)"
tls_block=""
if tls_block="$(_resolve_tls_block "$DOMAIN")"; then
  :
else
  warn "No MCP TLS cert for DOMAIN=${DOMAIN:-<unset>} — identity proxy expects https://127.0.0.1:8766 upstream"
  warn "Run install-portals with https-le or set SSH_OPS_MCP_TLS_CERT/KEY before enabling ssh-ops-mcp.service"
fi

install -d -m 0755 "$(dirname "$OUT")"
{
  while IFS= read -r line || [[ -n "$line" ]]; do
    case "$line" in
      *@MCP_PUBLISH@*)
        echo "${line//@MCP_PUBLISH@/$publish}"
        ;;
      *@SSH_OPS_DATA_REL@*)
        echo "${line//@SSH_OPS_DATA_REL@/$data_rel}"
        ;;
      '@MCP_TLS_LINES@')
        if [[ -n "$tls_block" ]]; then
          printf '%s\n' "$tls_block"
        fi
        ;;
      *)
        echo "$line"
        ;;
    esac
  done <"$TEMPLATE"
} >"$OUT"
chmod 0644 "$OUT"

say "Installed $OUT"
say "  PublishPort=${publish}"
say "  data volume=%h/${data_rel}"
if [[ -n "$tls_block" ]]; then
  say "  TLS DOMAIN=${DOMAIN:-<from cert paths>}"
fi

if ! command -v podman >/dev/null 2>&1; then
  warn "podman not found — quadlet written only"
  exit 0
fi

systemctl --user daemon-reload
systemctl --user enable ssh-ops-mcp.service 2>/dev/null || true
if [[ "$NO_RESTART" -eq 0 ]]; then
  systemctl --user reset-failed ssh-ops-mcp.service 2>/dev/null || true
  if systemctl --user restart ssh-ops-mcp.service; then
    sleep 2
    if systemctl --user is-active --quiet ssh-ops-mcp.service; then
      say "ssh-ops-mcp.service active"
    else
      warn "ssh-ops-mcp.service not active — journalctl --user -u ssh-ops-mcp -n 20"
      exit 1
    fi
  else
    warn "ssh-ops-mcp.service restart failed — journalctl --user -u ssh-ops-mcp -n 20"
    exit 1
  fi
fi
