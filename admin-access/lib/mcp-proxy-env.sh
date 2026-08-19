# shellcheck shell=bash
# Shared helpers for mcp-identity-proxy systemd drop-in (lego TLS, LAN bind).

mcp_proxy_portal_domain() {
  local portal_env="${CLAW_PORTAL_ENV:-$HOME/.claw-portals/config.env}"
  [[ -f "$portal_env" ]] || return 0
  grep -E '^DOMAIN=' "$portal_env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d "\"'" | xargs
}

# Prints cert path then key path when found.
mcp_proxy_resolve_tls() {
  local cert="${SSH_OPS_MCP_PROXY_TLS_CERT:-}" key="${SSH_OPS_MCP_PROXY_TLS_KEY:-}"
  if [[ -z "$cert" || -z "$key" ]]; then
    local domain lego
    domain="$(mcp_proxy_portal_domain)"
    lego="${SSH_OPS_MCP_TLS_DIR:-$HOME/mcp/acme/lego/certificates}"
    if [[ -n "$domain" && -f "$lego/${domain}.crt" && -f "$lego/${domain}.key" ]]; then
      cert="$lego/${domain}.crt"
      key="$lego/${domain}.key"
    fi
  fi
  if [[ -n "$cert" && -f "$cert" && -n "$key" && -f "$key" ]]; then
    printf '%s\n' "$cert" "$key"
  fi
}

mcp_proxy_scheme() {
  if mcp_proxy_resolve_tls >/dev/null; then
    printf 'https'
  else
    printf 'http'
  fi
}

# Resolve identity-proxy listen address (drop-in → portal LAN_IP → 127.0.0.1).
mcp_proxy_resolve_bind() {
  local bind="${SSH_OPS_MCP_PROXY_BIND:-${SSH_OPS_MCP_PROXY_HOST:-}}"
  local dropin portal_env
  if [[ -z "$bind" ]]; then
    dropin="${HOME}/.config/systemd/user/mcp-identity-proxy.service.d/clawlab.conf"
    if [[ -f "$dropin" ]]; then
      bind="$(grep -E '^Environment=SSH_OPS_MCP_PROXY_HOST=' "$dropin" 2>/dev/null \
        | head -1 | sed 's/^Environment=SSH_OPS_MCP_PROXY_HOST=//' || true)"
    fi
  fi
  if [[ -z "$bind" ]]; then
    portal_env="${CLAW_PORTAL_ENV:-$HOME/.claw-portals/config.env}"
    if [[ -f "$portal_env" ]]; then
      # shellcheck disable=SC1090
      source "$portal_env" 2>/dev/null || true
      bind="${LAN_IP:-}"
    fi
  fi
  printf '%s' "${bind:-127.0.0.1}"
}

# External clients (Cursor, Claude Desktop): portal domain + TLS when lego cert exists.
mcp_proxy_public_url() {
  local bind="${1:-127.0.0.1}" port="${2:-8767}"
  local domain scheme
  domain="$(mcp_proxy_portal_domain)"
  scheme="$(mcp_proxy_scheme)"
  if [[ "$scheme" == "https" && -n "$domain" ]]; then
    printf '%s://%s:%s/mcp' "$scheme" "$domain" "$port"
  elif [[ "$bind" != "127.0.0.1" && "$bind" != "::1" ]]; then
    printf '%s://%s:%s/mcp' "$scheme" "$bind" "$port"
  else
    printf '%s://127.0.0.1:%s/mcp' "$scheme" "$port"
  fi
}

# OpenClaw gateway on the same host: portal domain when TLS (cert SAN matches).
# Pair with ensure-mcp-local-hosts.sh so the domain resolves to LAN_IP locally.
mcp_proxy_gateway_url() {
  local bind="${1:-127.0.0.1}" port="${2:-8767}"
  local domain scheme
  domain="$(mcp_proxy_portal_domain)"
  scheme="$(mcp_proxy_scheme)"
  if [[ "$scheme" == "https" && -n "$domain" ]]; then
    printf '%s://%s:%s/mcp' "$scheme" "$domain" "$port"
  elif [[ "$bind" != "127.0.0.1" && "$bind" != "::1" ]]; then
    printf '%s://%s:%s/mcp' "$scheme" "$bind" "$port"
  else
    printf '%s://127.0.0.1:%s/mcp' "$scheme" "$port"
  fi
}

# Warn when co-located clients need /etc/hosts for domain -> LAN_IP (TLS + no hairpin).
mcp_proxy_local_hosts_ok() {
  local portal_env="${CLAW_PORTAL_ENV:-$HOME/.claw-portals/config.env}"
  local domain lan_ip resolved
  [[ -f "$portal_env" ]] || return 0
  # shellcheck disable=SC1090
  source "$portal_env" 2>/dev/null || true
  domain="${DOMAIN:-}"
  lan_ip="${LAN_IP:-}"
  [[ -n "$domain" && -n "$lan_ip" ]] || return 0
  mcp_proxy_resolve_tls >/dev/null || return 0
  resolved="$(getent ahostsv4 "$domain" 2>/dev/null | awk 'NR==1{print $1; exit}' || true)"
  [[ "$resolved" == "$lan_ip" ]]
}

mcp_proxy_warn_local_hosts() {
  local portal_env="${CLAW_PORTAL_ENV:-$HOME/.claw-portals/config.env}"
  local domain lan_ip resolved
  [[ -f "$portal_env" ]] || return 0
  # shellcheck disable=SC1090
  source "$portal_env" 2>/dev/null || true
  domain="${DOMAIN:-}"
  lan_ip="${LAN_IP:-}"
  [[ -n "$domain" && -n "$lan_ip" ]] || return 0
  mcp_proxy_resolve_tls >/dev/null || return 0
  if mcp_proxy_local_hosts_ok; then
    return 0
  fi
  resolved="$(getent ahostsv4 "$domain" 2>/dev/null | awk 'NR==1{print $1; exit}' || true)"
  echo ">> Co-located MCP: ${domain} should resolve to ${lan_ip} (lego TLS + avoid hairpin)"
  if [[ -n "$resolved" && "$resolved" != "$lan_ip" ]]; then
    echo ">> Now: ${domain} -> ${resolved} (expected ${lan_ip})"
  fi
  echo ">> Fix: bash admin-access/ensure-mcp-local-hosts.sh"
}

# Write ~/.config/systemd/user/mcp-identity-proxy.service.d/clawlab.conf
mcp_proxy_write_dropin() {
  local upstream_host="${1:-127.0.0.1}"
  local bind="${2:-127.0.0.1}"
  local data_dir="${3:-$HOME/.clawlab/ssh-ops/data}"
  local unit_dir="${HOME}/.config/systemd/user"
  local override_dir="${unit_dir}/mcp-identity-proxy.service.d"
  install -d -m 0755 "$override_dir"
  local tls_block=""
  if tls_paths="$(mcp_proxy_resolve_tls)"; then
    local tls_cert tls_key
    tls_cert="${tls_paths%%$'\n'*}"
    tls_key="${tls_paths#*$'\n'}"
    tls_block="Environment=SSH_OPS_MCP_PROXY_TLS_CERT=${tls_cert}
Environment=SSH_OPS_MCP_PROXY_TLS_KEY=${tls_key}"
  fi
  cat >"${override_dir}/clawlab.conf" <<EOF
[Service]
Environment=SSH_OPS_MCP_UPSTREAM=https://${upstream_host}:8766
Environment=SSH_OPS_MCP_PROXY_HOST=${bind}
Environment=SSH_OPS_ENV=${data_dir}/.env
Environment=SSH_OPS_KEYFILE=${data_dir}/master.key
${tls_block}
EOF
}
