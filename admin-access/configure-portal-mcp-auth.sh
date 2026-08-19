#!/usr/bin/env bash
# Wire MCP identity proxy + OpenClaw MCP auth after install-portals.sh (step 3).
#
# - Identity proxy on LAN :8767 (TLS when lego cert present)
# - clawlab-mcp-identity plugin (clawBind from portal hub)
# - Shared MCP bearer in openclaw.json (optional; skops_ PAT from set-openclaw-mcp-pat.sh is preserved)
set -Eeuo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PORTAL_ENV="${CLAW_PORTAL_ENV:-$HOME/.claw-portals/config.env}"

if [[ -f "$PORTAL_ENV" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$PORTAL_ENV"
  set +a
fi

LAN_IP="${LAN_IP:-127.0.0.1}"
DOMAIN="${DOMAIN:-lab.example.com}"
PORT_PORTAL="${PORT_PORTAL:-8443}"
SCHEME="${SCHEME:-https}"
if [[ "${TLS_MODE:-}" == "http" ]]; then
  SCHEME=http
  PORT_PORTAL="${PORT_PORTAL:-8083}"
fi

SSH_OPS_MCP_PROXY_BIND="${SSH_OPS_MCP_PROXY_BIND:-$LAN_IP}" \
SSH_OPS_DATA="${SSH_OPS_DATA:-$HOME/.clawlab/ssh-ops/data}" \
  bash "$REPO/admin-access/configure-openclaw-mcp-identity.sh"

if [[ -f "$HOME/.openclaw/openclaw.json" ]]; then
  DOMAIN="$DOMAIN" PORT_PORTAL="$PORT_PORTAL" SCHEME="$SCHEME" \
    bash "$REPO/admin-access/sync-openclaw-gateway-mcp-auth.sh"
else
  echo "skip sync-openclaw-gateway-mcp-auth: no ~/.openclaw/openclaw.json"
fi

echo ""
echo "MCP auth summary:"
echo "  OpenClaw (recommended): portal hub → Open OpenClaw ↗ (includes clawBind for identity)"
echo "  OpenClaw (bookmarks):   bash admin-access/set-openclaw-mcp-pat.sh  # skops_… PAT"
echo "  Cursor / external:      portal hub → MCP tokens → Bearer skops_… on :8767/mcp"
mcp_proxy_warn_local_hosts
