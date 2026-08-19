#!/usr/bin/env bash
# Map portal DOMAIN -> LAN_IP in /etc/hosts for co-located OpenClaw + MCP identity proxy.
# Needed when :8767 uses lego TLS (cert is for DOMAIN, not LAN_IP) and public DNS hairpins.
set -Eeuo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib/mcp-proxy-env.sh
source "$REPO/admin-access/lib/mcp-proxy-env.sh"

PORTAL_ENV="${CLAW_PORTAL_ENV:-$HOME/.claw-portals/config.env}"
[[ -f "$PORTAL_ENV" ]] || {
  echo "error: missing $PORTAL_ENV" >&2
  exit 1
}
# shellcheck disable=SC1090
source "$PORTAL_ENV"

domain="${DOMAIN:-}"
lan_ip="${LAN_IP:-}"
[[ -n "$domain" && -n "$lan_ip" ]] || {
  echo "error: DOMAIN and LAN_IP must be set in $PORTAL_ENV" >&2
  exit 1
}

if mcp_proxy_local_hosts_ok; then
  echo "OK: ${domain} already resolves to ${lan_ip}"
  exit 0
fi

line="${lan_ip} ${domain}"
if [[ ! -w /etc/hosts ]]; then
  if ! command -v sudo >/dev/null 2>&1; then
    echo "error: need sudo to update /etc/hosts with: ${line}" >&2
    exit 1
  fi
  if grep -qE "[[:space:]]${domain}([[:space:]]|$)" /etc/hosts 2>/dev/null; then
    echo "Removing stale ${domain} entries from /etc/hosts…"
    sudo sed -i "/[[:space:]]${domain}\(\s\|$)/d" /etc/hosts
  fi
  echo "${line}" | sudo tee -a /etc/hosts >/dev/null
else
  if grep -qE "[[:space:]]${domain}([[:space:]]|$)" /etc/hosts 2>/dev/null; then
    sed -i "/[[:space:]]${domain}\(\s\|$)/d" /etc/hosts
  fi
  printf '%s\n' "$line" >>/etc/hosts
fi

if mcp_proxy_local_hosts_ok; then
  echo "OK: added ${line}"
  exit 0
fi

echo "error: ${domain} still does not resolve to ${lan_ip}" >&2
exit 1
