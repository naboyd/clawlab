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
  sleep 1
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

start_claw_auth() {
  load_portal_env
  start_bg claw-auth env \
    CLAW_AUTH_HOME="$HOME/.claw-auth" \
    CLAW_AUTH_HOST=127.0.0.1 \
    CLAW_AUTH_PORT=8780 \
    CLAW_AUTH_SECURE=0 \
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
  if command -v openclaw >/dev/null 2>&1; then
    start_bg openclaw-gateway openclaw gateway start || \
      start_bg openclaw-gateway openclaw gateway run --bind 127.0.0.1 --port 18789
  else
    warn "openclaw CLI not found"
  fi
}

start_nginx() {
  command -v nginx >/dev/null 2>&1 || { warn "nginx not installed"; return 1; }
  [[ -f "$CLAWLAB_NGINX/nginx.conf" ]] || { warn "missing $CLAWLAB_NGINX/nginx.conf — run install-clawstack.sh local-full first"; return 1; }
  if pid_alive "$RUN/nginx.pid"; then
    info "nginx already running"
    return 0
  fi
  nginx -t -c "$CLAWLAB_NGINX/nginx.conf" -p "$CLAWLAB_NGINX" 2>/dev/null || {
    warn "nginx config test failed"
    return 1
  }
  nginx -c "$CLAWLAB_NGINX/nginx.conf" -p "$CLAWLAB_NGINX"
  if [[ -f "$CLAWLAB_NGINX/logs/nginx.pid" ]]; then
    cp "$CLAWLAB_NGINX/logs/nginx.pid" "$RUN/nginx.pid"
  fi
  info "started nginx on http://127.0.0.1:${LOCAL_FULL_PORT:-8083}"
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

cmd_start() {
  log "Starting local-full stack"
  start_claw_auth
  start_defenseclaw_webgui
  start_openclaw_gateway
  start_ssh_ops
  start_nginx || true
  cmd_status
}

cmd_stop() {
  log "Stopping local-full stack"
  stop_nginx
  stop_bg claw-auth
  stop_bg defenseclaw-webgui
  stop_bg openclaw-gateway
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
    else
      printf '  --   %-22s not running\n' "$s"
    fi
  done
  if command -v podman >/dev/null 2>&1; then
    CLAWLAB_MANAGE_MCP=1 SSH_OPS_DIR="$REPO/ssh-ops-mcp" bash "$REPO/ssh-ops-mcp/podctl.sh" --status 2>/dev/null || true
  fi
  curl -fsS "http://127.0.0.1:8780/healthz" >/dev/null 2>&1 && echo "  OK   claw-auth healthz" || echo "  --   claw-auth healthz"
  curl -fsS "http://127.0.0.1:${LOCAL_FULL_PORT:-8083}/" -o /dev/null 2>&1 && echo "  OK   portal :${LOCAL_FULL_PORT:-8083}" || echo "  --   portal :${LOCAL_FULL_PORT:-8083} (login required or nginx down)"
}

ACTION="${1:-status}"
case "$ACTION" in
  start) cmd_start ;;
  stop) cmd_stop ;;
  restart) cmd_stop; sleep 1; cmd_start ;;
  status) cmd_status ;;
  -h|--help)
    sed -n '1,12p' "$0" | sed 's/^# \{0,1\}//'
    ;;
  *) die "Unknown action: $ACTION (try start|stop|status|restart)" ;;
esac
