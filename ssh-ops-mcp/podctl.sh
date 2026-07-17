#!/usr/bin/env bash
#
# podctl.sh — manage the ssh-ops Podman containers on this machine.
#
#   ./podctl.sh                 ensure containers are up (start only if stopped)
#   ./podctl.sh --restart       restart running containers in place (fast)
#   ./podctl.sh --recreate      remove + re-run containers (fresh, same image)
#   ./podctl.sh --build         rebuild the image, then recreate containers
#   ./podctl.sh --build --no-cache   force a clean rebuild, then recreate
#   ./podctl.sh --status        just show status, change nothing
#   ./podctl.sh --logs          append combined container logs to the log file
#   ./podctl.sh --follow        also stream combined logs live afterwards
#
# It manages ssh-ops-gui (:8765) and optionally ssh-ops-mcp (:8766) when
# CLAWLAB_MANAGE_MCP=1 (local-full / lab stack).
set -euo pipefail

# ---- config (override via env, or edit) -----------------------------------
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_CLAWLAB_REPO="$(cd "$_SCRIPT_DIR/.." && pwd)"
PROJECT_DIR="${SSH_OPS_DIR:-${_CLAWLAB_REPO}/ssh-ops-mcp}"
IMAGE="${SSH_OPS_IMAGE:-ssh-ops:latest}"
DATA_DIR="${SSH_OPS_DATA:-$HOME/.clawlab/ssh-ops/data}"
SSH_DIR="${SSH_OPS_SSH:-$HOME/.ssh}"
CLAWLAB_REPO="${CLAWLAB_REPO:-$_CLAWLAB_REPO}"
GUI_PUBLISH="${SSH_OPS_GUI_PUBLISH:-127.0.0.1:8765:8765}"
MCP_PUBLISH="${SSH_OPS_MCP_PUBLISH:-127.0.0.1:8766:8766}"
PORTAL_ENV="${CLAW_PORTAL_ENV:-$HOME/.claw-portals/config.env}"
LOG_DIR="${SSH_OPS_LOG_DIR:-$HOME/.clawlab/ssh-ops/logs}"
LOG_FILE="$LOG_DIR/pods.log"

# Long-running containers: "name|mode".
MANAGED=( "ssh-ops-gui|gui" )
if [[ "${CLAWLAB_MANAGE_MCP:-0}" == "1" ]]; then
  MANAGED+=( "ssh-ops-mcp|mcp" )
fi

# ---- helpers --------------------------------------------------------------
say() { printf '>> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

usage() { sed -n '3,20p' "$0" | sed 's/^# \{0,1\}//'; }

need_podman() { command -v podman >/dev/null 2>&1 || die "podman not found on PATH"; }

is_running() { podman ps --format '{{.Names}}' 2>/dev/null | grep -qx "$1"; }

build_image() {
  say "building $IMAGE${NOCACHE:+ (no cache)} from $PROJECT_DIR"
  podman build ${NOCACHE:+--no-cache} -t "$IMAGE" "$PROJECT_DIR"
}

start_container() {
  local name="$1" mode="$2"
  podman rm -f "$name" >/dev/null 2>&1 || true
  mkdir -p "$DATA_DIR" "$LOG_DIR"
  local -a env_file=()
  [[ -f "$PORTAL_ENV" ]] && env_file=(--env-file "$PORTAL_ENV")
  case "$mode" in
    gui)
      local rules_dir="${DEFENSECLAW_RULES_DIR:-$HOME/.defenseclaw/policies/guardrail/strict/rules}"
      local -a rules_mount=()
      if [[ -d "$rules_dir" ]]; then
        rules_mount=(-v "$rules_dir:/defenseclaw-rules:ro")
      fi
      podman run -d --name "$name" --restart unless-stopped \
        -p "$GUI_PUBLISH" \
        "${env_file[@]}" \
        -e CLAW_AUTH_REQUIRED=1 \
        -e PORTAL_MOUNT_PATH=/ssh-ops \
        -e CLAWLAB_REPO=/clawlab \
        -e DEFENSECLAW_WEBGUI_URL=http://host.containers.internal:8770 \
        -e DEFENSECLAW_RULES_DIR=/defenseclaw-rules \
        --add-host=host.containers.internal:host-gateway \
        -v "$DATA_DIR:/data" \
        -v "$SSH_DIR:/root/.ssh:ro" \
        -v "$CLAWLAB_REPO:/clawlab:ro" \
        -v "$HOME/.claw-auth/users.db:/claw-auth/users.db:ro" \
        "${rules_mount[@]}" \
        -e CLAW_AUTH_DB=/claw-auth/users.db \
        -e SSH_OPS_RBAC=1 \
        "$IMAGE" gui >/dev/null
      ;;
    mcp)
      podman run -d --name "$name" --restart unless-stopped \
        -p "$MCP_PUBLISH" \
        -e SSH_OPS_MCP_TRANSPORT=streamable-http \
        -e SSH_OPS_MCP_HOST=0.0.0.0 \
        -e SSH_OPS_MCP_PORT=8766 \
        -e SSH_OPS_CONFIG=/data/hosts.yaml \
        --add-host=host.containers.internal:host-gateway \
        -v "$DATA_DIR:/data" \
        -v "$SSH_DIR:/root/.ssh:ro" \
        -v "$HOME/.claw-auth/users.db:/claw-auth/users.db:ro" \
        -e CLAW_AUTH_DB=/claw-auth/users.db \
        -e SSH_OPS_RBAC=1 \
        "$IMAGE" mcp >/dev/null
      ;;
    *) die "unknown container mode '$mode'";;
  esac
  say "(re)started $name ($mode)"
}

ensure_up() {
  local name="$1" mode="$2"
  if is_running "$name"; then say "$name already running"; else start_container "$name" "$mode"; fi
}

restart_container() {
  local name="$1" mode="$2"
  if podman container exists "$name" 2>/dev/null; then
    podman restart "$name" >/dev/null && say "restarted $name (in place)"
  else
    say "$name did not exist — creating it"
    start_container "$name" "$mode"
  fi
}

status() {
  echo "== managed containers =="
  local name
  for entry in "${MANAGED[@]}"; do
    name="${entry%%|*}"
    if is_running "$name"; then echo "  $name: running"; else echo "  $name: NOT running"; fi
  done
  echo "== all containers from $IMAGE =="
  podman ps -a --filter "ancestor=$IMAGE" --format '  {{.Names}}\t{{.Status}}' 2>/dev/null || true
}

collect_logs() {
  mkdir -p "$LOG_DIR"
  say "appending combined logs to $LOG_FILE"
  {
    echo "===================== $(date) ====================="
    for name in $(podman ps -a --filter "ancestor=$IMAGE" --format '{{.Names}}' 2>/dev/null); do
      echo "--------------------- [$name] ---------------------"
      podman logs "$name" 2>&1 | sed "s/^/[$name] /"
    done
  } >> "$LOG_FILE"
}

follow_logs() {
  mkdir -p "$LOG_DIR"
  say "streaming combined logs -> $LOG_FILE (Ctrl-C to stop)"
  trap 'kill $(jobs -p) 2>/dev/null || true' EXIT INT TERM
  local any=0
  for name in $(podman ps --filter "ancestor=$IMAGE" --format '{{.Names}}' 2>/dev/null); do
    any=1
    ( podman logs -f "$name" 2>&1 | sed "s/^/[$name] /" | tee -a "$LOG_FILE" ) &
  done
  [ "$any" = 0 ] && { say "no running containers to follow"; return; }
  wait
}

# ---- args -----------------------------------------------------------------
ACTION=""
DO_BUILD=0
FOLLOW=0
NOCACHE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --build)    DO_BUILD=1 ;;
    --no-cache) NOCACHE=1 ;;
    --restart)  ACTION="restart" ;;
    --recreate) ACTION="recreate" ;;
    --status)   ACTION="status" ;;
    --logs)     ACTION="logs" ;;
    --follow)   FOLLOW=1 ;;
    -h|--help)  usage; exit 0 ;;
    *) die "unknown option: $1 (see --help)";;
  esac
  shift
done

# --build needs a full recreate to pick up the new image; default is ensure-up.
if [ "$DO_BUILD" = 1 ] && [ -z "$ACTION" ]; then ACTION="recreate"; fi
[ -z "$ACTION" ] && ACTION="up"

# ---- main -----------------------------------------------------------------
need_podman
case "$ACTION" in
  status) status ;;
  logs)   collect_logs; echo "log file: $LOG_FILE" ;;
  up|restart|recreate)
    [ "$DO_BUILD" = 1 ] && build_image
    for entry in "${MANAGED[@]}"; do
      name="${entry%%|*}"; mode="${entry##*|}"
      case "$ACTION" in
        up)       ensure_up "$name" "$mode" ;;
        restart)  restart_container "$name" "$mode" ;;
        recreate) start_container "$name" "$mode" ;;
      esac
    done
    echo; status; echo; collect_logs
    if [ "$FOLLOW" = 1 ]; then echo; follow_logs; fi
    echo
    say "done."
    ;;
esac
