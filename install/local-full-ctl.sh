#!/usr/bin/env bash
# local-full-ctl.sh — start/stop loopback clawlab stack (no systemd required).
#
# Usage:
#   bash install/local-full-ctl.sh start
#   bash install/local-full-ctl.sh stop
#   bash install/local-full-ctl.sh status
#   bash install/local-full-ctl.sh restart
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib/clawlab-platform.sh
source "$SCRIPT_DIR/lib/clawlab-platform.sh"
# shellcheck source=lib/clawlab-local-full.sh
source "$SCRIPT_DIR/lib/clawlab-local-full.sh"

REPO="$(clawlab_repo_root "$0")"
RUN="$CLAWLAB_RUN"
mkdir -p "$RUN"

export PATH="$HOME/.local/bin:$HOME/.npm-global/bin:$PATH"
clawlab_prepend_openclaw_node_path || true

log()  { printf '==> %s\n' "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*" >&2; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

load_portal_env() {
  if [[ -f "$HOME/.claw-portals/config.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$HOME/.claw-portals/config.env"
    set +a
  fi
  CLAWLAB_REPO="${CLAWLAB_REPO:-$REPO}"
  # shellcheck disable=SC1091
  source "$REPO/claw-portals/ensure-venv.sh"
  ensure_clawlab_venv
}

pid_alive() {
  local pidfile="$1"
  [[ -f "$pidfile" ]] || return 1
  local pid
  pid="$(cat "$pidfile" 2>/dev/null)" || return 1
  kill -0 "$pid" 2>/dev/null
}

start_bg() {
  local name="$1" pidfile="$RUN/$1.pid" logfile="$RUN/$1.log"
  shift
  if pid_alive "$pidfile"; then
    info "$name already running (pid $(cat "$pidfile"))"
    return 0
  fi
  : >"$logfile"
  nohup "$@" >>"$logfile" 2>&1 &
  echo $! >"$pidfile"
  sleep 2
  if pid_alive "$pidfile"; then
    info "started $name (pid $(cat "$pidfile"), log $logfile)"
  else
    warn "failed to start $name — see $logfile"
    return 1
  fi
}

stop_bg() {
  local name="$1" pidfile="$RUN/$1.pid"
  if pid_alive "$pidfile"; then
    kill "$(cat "$pidfile")" 2>/dev/null || true
    rm -f "$pidfile"
    info "stopped $name"
  fi
}

stop_openclaw_gateway() {
  stop_bg openclaw-gateway
  if port_open "${OPENCLAW_GATEWAY_PORT:-18789}"; then
    pkill -f "dist/index.js gateway run --bind loopback --port ${OPENCLAW_GATEWAY_PORT:-18789}" 2>/dev/null || true
    pkill -f "dist/index.js gateway --port ${OPENCLAW_GATEWAY_PORT:-18789}" 2>/dev/null || true
    pkill -f "openclaw gateway run --port ${OPENCLAW_GATEWAY_PORT:-18789}" 2>/dev/null || true
  fi
}

port_open() {
  local port="$1"
  python3 - "$port" <<'PY'
import socket, sys
s = socket.socket()
s.settimeout(0.3)
try:
    s.connect(("127.0.0.1", int(sys.argv[1])))
    sys.exit(0)
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
}

load_openclaw_env() {
  if [[ -f "$HOME/.openclaw/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$HOME/.openclaw/.env"
    set +a
  fi
  if [[ -f "$HOME/.openclaw/gateway.systemd.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$HOME/.openclaw/gateway.systemd.env"
    set +a
  fi
  export OPENCLAW_GATEWAY_PORT="${OPENCLAW_GATEWAY_PORT:-18789}"
}

ensure_openclaw_gateway_mode() {
  local oc="$HOME/.openclaw/openclaw.json"
  [[ -f "$oc" ]] || return 0
  python3 - "$oc" <<'PY'
import json, sys
p = sys.argv[1]
with open(p) as f:
    d = json.load(f)
gw = d.setdefault("gateway", {})
changed = False
if gw.get("mode") != "local":
    gw["mode"] = "local"
    changed = True
if "host" in gw:
    gw.pop("host", None)
    changed = True
if changed:
    with open(p, "w") as f:
        json.dump(d, f, indent=1)
    print("patched gateway (mode=local, removed obsolete host key)")
PY
}

openclaw_gateway_js() {
  local candidate oc="$HOME/.local/bin/openclaw"
  for candidate in \
    "$HOME/src/openclaw/dist/index.js" \
    "$HOME/src/openclaw/openclaw.mjs"; do
    [[ -f "$candidate" ]] && { printf '%s' "$candidate"; return 0; }
  done
  if [[ -e "$oc" ]]; then
    python3 - "$oc" <<'PY'
import os, sys
print(os.path.realpath(sys.argv[1]))
PY
    return 0
  fi
  return 1
}

ensure_nginx_mime_types() {
  local mt="$CLAWLAB_NGINX/mime.types"
  [[ -f "$mt" ]] && return 0
  for src in /opt/homebrew/etc/nginx/mime.types /usr/local/etc/nginx/mime.types /etc/nginx/mime.types; do
    if [[ -f "$src" ]]; then cp "$src" "$mt"; return 0; fi
  done
  cat >"$mt" <<'MIME'
types {
    text/html                             html htm;
    text/css                              css;
    application/javascript              js;
    application/json                      json;
    image/png                             png;
    image/jpeg                            jpeg jpg;
    image/svg+xml                         svg svgz;
    font/woff                             woff;
    font/woff2                            woff2;
}
MIME
}

start_claw_auth() {
  load_portal_env
  local -a extra_env=()
  if [[ -f "$HOME/.openclaw/.env" ]]; then
    # shellcheck disable=SC1091
    set -a; source "$HOME/.openclaw/.env"; set +a
  fi
  [[ -n "${OPENCLAW_GATEWAY_TOKEN:-}" ]] && extra_env+=(OPENCLAW_GATEWAY_TOKEN="$OPENCLAW_GATEWAY_TOKEN")
  [[ -n "${SCHEME:-}" ]] && extra_env+=(SCHEME="$SCHEME")
  start_bg claw-auth env \
    CLAW_AUTH_HOME="$HOME/.claw-auth" \
    CLAW_AUTH_HOST=127.0.0.1 \
    CLAW_AUTH_PORT=8780 \
    CLAW_AUTH_SECURE=0 \
    "${extra_env[@]}" \
    "$CLAW_PYTHON" "$REPO/claw-auth/authd.py"
}

start_defenseclaw_webgui() {
  load_portal_env
  start_bg defenseclaw-webgui env \
    DEFENSECLAW_HOME="$HOME/.defenseclaw" \
    DEFENSECLAW_CONFIG="$HOME/.defenseclaw/config.yaml" \
    DEFENSECLAW_GUI_HOST=127.0.0.1 \
    DEFENSECLAW_GUI_PORT=8770 \
    PORTAL_MOUNT_PATH=/defenseclaw \
    CLAWLAB_REPO="$REPO" \
    "$CLAW_PYTHON" "$REPO/defenseclaw-webgui/webgui.py"
}

start_openclaw_gateway() {
  if [[ "$CLAWLAB_SVC" == "systemd-user" ]] && systemctl --user is-active openclaw-gateway.service >/dev/null 2>&1; then
    info "openclaw-gateway systemd unit already active"
    return 0
  fi
  if port_open "${OPENCLAW_GATEWAY_PORT:-18789}"; then
    info "openclaw gateway already listening on :${OPENCLAW_GATEWAY_PORT:-18789}"
    return 0
  fi
  load_openclaw_env
  ensure_openclaw_gateway_mode
  local js port="${OPENCLAW_GATEWAY_PORT:-18789}"
  if js="$(openclaw_gateway_js 2>/dev/null)" && [[ -f "$js" ]]; then
    start_bg openclaw-gateway env HOME="$HOME" OPENCLAW_GATEWAY_PORT="$port" \
      node "$js" gateway run --bind loopback --port "$port" --force \
      || warn "failed to start openclaw gateway — see $RUN/openclaw-gateway.log"
    return 0
  fi
  if command -v openclaw >/dev/null 2>&1; then
    start_bg openclaw-gateway env HOME="$HOME" OPENCLAW_GATEWAY_PORT="$port" \
      openclaw gateway run --bind loopback --port "$port" --force \
      || warn "failed to start openclaw gateway — see $RUN/openclaw-gateway.log"
    return 0
  fi
  warn "openclaw not found — build via install-clawstack.sh"
}

start_nginx() {
  if ! command -v nginx >/dev/null 2>&1; then
    if [[ "$CLAWLAB_PKG" == "brew" ]]; then
      warn "nginx not installed — running: brew install nginx"
      brew install nginx || { warn "brew install nginx failed"; return 1; }
    elif [[ "$CLAWLAB_PKG" == "apt" ]]; then
      warn "nginx not installed — running: sudo apt-get install nginx"
      sudo apt-get install -y nginx || { warn "apt install nginx failed"; return 1; }
    else
      warn "nginx not installed (brew install nginx)"
      return 1
    fi
  fi
  load_portal_env
  clawlab_local_full_write_nginx "$REPO"
  ensure_nginx_mime_types
  if ! nginx -t -c "$CLAWLAB_NGINX/nginx.conf" -p "$CLAWLAB_NGINX" 2>"$RUN/nginx-test.log"; then
    warn "nginx config test failed — see $RUN/nginx-test.log"
    tail -3 "$RUN/nginx-test.log" >&2 || true
    return 1
  fi
  if pid_alive "$RUN/nginx.pid" || port_open "${LOCAL_FULL_PORT:-8083}"; then
    nginx -s reload -c "$CLAWLAB_NGINX/nginx.conf" -p "$CLAWLAB_NGINX" 2>/dev/null \
      && info "reloaded nginx (http://127.0.0.1:${LOCAL_FULL_PORT:-8083})" \
      || info "nginx already running"
    return 0
  fi
  nginx -c "$CLAWLAB_NGINX/nginx.conf" -p "$CLAWLAB_NGINX"
  if [[ -f "$CLAWLAB_NGINX/logs/nginx.pid" ]]; then
    cp "$CLAWLAB_NGINX/logs/nginx.pid" "$RUN/nginx.pid"
  fi
  sleep 1
  if port_open "${LOCAL_FULL_PORT:-8083}"; then
    info "started nginx on http://127.0.0.1:${LOCAL_FULL_PORT:-8083}"
  else
    warn "nginx started but :${LOCAL_FULL_PORT:-8083} not reachable — see $CLAWLAB_NGINX/logs/error.log"
    return 1
  fi
}

stop_nginx() {
  if [[ -f "$CLAWLAB_NGINX/logs/nginx.pid" ]]; then
    nginx -s stop -c "$CLAWLAB_NGINX/nginx.conf" -p "$CLAWLAB_NGINX" 2>/dev/null || true
  fi
  rm -f "$RUN/nginx.pid"
}

start_ssh_ops() {
  export CLAWLAB_MANAGE_MCP=1
  export SSH_OPS_DIR="$REPO/ssh-ops-mcp"
  export SSH_OPS_DATA="$CLAWLAB_SSH_OPS_DATA"
  export CLAWLAB_REPO="$REPO"
  export SSH_OPS_GUI_PUBLISH="127.0.0.1:8765:8765"
  export SSH_OPS_MCP_PUBLISH="127.0.0.1:8766:8766"
  bash "$REPO/ssh-ops-mcp/podctl.sh" --build --recreate
}

start_mcp_identity_proxy() {
  load_portal_env
  [[ -f "$REPO/ssh-ops-mcp/mcp_identity_proxy.py" ]] || return 0
  if port_open 8767; then
    info "mcp-identity-proxy already listening on :8767"
    return 0
  fi
  start_bg mcp-identity-proxy env \
    CLAW_AUTH_DB="$HOME/.claw-auth/users.db" \
    SSH_OPS_MCP_UPSTREAM="http://127.0.0.1:8766" \
    SSH_OPS_MCP_PROXY_HOST=127.0.0.1 \
    SSH_OPS_MCP_PROXY_PORT=8767 \
    SSH_OPS_MCP_PROXY_VERIFY_TLS=0 \
    SSH_OPS_DATA="$CLAWLAB_SSH_OPS_DATA" \
    SSH_OPS_ENV="$CLAWLAB_SSH_OPS_DATA/.env" \
    SSH_OPS_KEYFILE="$CLAWLAB_SSH_OPS_DATA/master.key" \
    "$CLAW_PYTHON" "$REPO/ssh-ops-mcp/mcp_identity_proxy.py" \
    || warn "mcp-identity-proxy failed — see $RUN/mcp-identity-proxy.log"
}

start_aux_services() {
  local dc="$HOME/.defenseclaw"
  if [[ -f "$dc/webex-bridge/dc-webex-bridge.py" ]]; then
    start_bg dc-webex-bridge env DEFENSECLAW_HOME="$dc" \
      "$CLAW_PYTHON" "$dc/webex-bridge/dc-webex-bridge.py" \
      || warn "dc-webex-bridge failed — see $RUN/dc-webex-bridge.log"
  fi
}

cmd_start() {
  log "Starting local-full stack"
  clawlab_local_full_ensure_hosts_inventory "$REPO"
  start_claw_auth
  start_defenseclaw_webgui
  start_openclaw_gateway
  start_ssh_ops
  start_mcp_identity_proxy
  start_aux_services
  start_nginx || die "nginx required for local-full portal — fix errors above and retry"
  clawlab_local_full_ensure_guardrails "$REPO" || true
  cmd_status
}

cmd_stop() {
  log "Stopping local-full stack"
  stop_nginx
  stop_bg claw-auth
  stop_bg defenseclaw-webgui
  stop_bg mcp-identity-proxy
  stop_bg dc-webex-bridge
  stop_openclaw_gateway
  if command -v podman >/dev/null 2>&1; then
    podman rm -f ssh-ops-gui ssh-ops-mcp 2>/dev/null || true
    info "stopped ssh-ops podman containers"
  fi
}

cmd_status() {
  echo "--- local-full services ---"
  for s in claw-auth defenseclaw-webgui openclaw-gateway nginx; do
    if pid_alive "$RUN/$s.pid"; then
      printf '  OK   %-22s pid %s\n' "$s" "$(cat "$RUN/$s.pid")"
    elif [[ "$s" == "openclaw-gateway" ]] && port_open "${OPENCLAW_GATEWAY_PORT:-18789}"; then
      printf '  OK   %-22s listening :%s\n' "$s" "${OPENCLAW_GATEWAY_PORT:-18789}"
    elif [[ "$s" == "nginx" ]] && port_open "${LOCAL_FULL_PORT:-8083}"; then
      printf '  OK   %-22s listening :%s\n' "$s" "${LOCAL_FULL_PORT:-8083}"
    else
      printf '  --   %-22s not running\n' "$s"
      if [[ -f "$RUN/$s.log" ]]; then
        tail -3 "$RUN/$s.log" 2>/dev/null | sed 's/^/         log: /' || true
      fi
    fi
  done
  if command -v podman >/dev/null 2>&1; then
    CLAWLAB_MANAGE_MCP=1 SSH_OPS_DIR="$REPO/ssh-ops-mcp" bash "$REPO/ssh-ops-mcp/podctl.sh" --status 2>/dev/null || true
  fi
  curl -fsS "http://127.0.0.1:8780/healthz" >/dev/null 2>&1 && echo "  OK   claw-auth healthz" || echo "  --   claw-auth healthz"
  if curl -fsS "http://127.0.0.1:${LOCAL_FULL_PORT:-8083}/" -o /dev/null 2>/dev/null; then
    echo "  OK   portal :${LOCAL_FULL_PORT:-8083}"
  elif curl -fsS -o /dev/null -w "%{http_code}" "http://127.0.0.1:${LOCAL_FULL_PORT:-8083}/" 2>/dev/null | grep -q '^30'; then
    echo "  OK   portal :${LOCAL_FULL_PORT:-8083} (auth redirect — expected without login)"
  elif port_open "${LOCAL_FULL_PORT:-8083}"; then
    echo "  OK   portal :${LOCAL_FULL_PORT:-8083} (listening)"
  else
    echo "  --   portal :${LOCAL_FULL_PORT:-8083} (nginx down — brew install nginx; bash install/local-full-ctl.sh restart)"
  fi
}

ACTION="${1:-status}"
case "$ACTION" in
  start) cmd_start ;;
  stop) cmd_stop ;;
  restart) cmd_stop; sleep 1; cmd_start ;;
  doctor) clawlab_local_full_doctor "$REPO" ;;
  status) cmd_status ;;
  -h|--help)
    sed -n '1,12p' "$0" | sed 's/^# \{0,1\}//'
    echo "  doctor  Mac policy prerequisites (SSH inventory, revshell rules, MCP)"
    ;;
  *) die "Unknown action: $ACTION (try start|stop|status|restart|doctor)" ;;
esac
