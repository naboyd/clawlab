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
# It manages the long-running admin GUI container (ssh-ops-gui). The MCP server
# is launched by the desktop app itself (podman run ... mcp), not by this script
# — but its logs ARE captured here, since we collect from every container built
# on the ssh-ops image.
set -euo pipefail

# ---- config (override via env, or edit) -----------------------------------
PROJECT_DIR="${SSH_OPS_DIR:-$HOME/ssh_mcp/ssh_ops_mcp}"
IMAGE="${SSH_OPS_IMAGE:-ssh-ops:latest}"
DATA_DIR="${SSH_OPS_DATA:-$PROJECT_DIR/data}"
SSH_DIR="${SSH_OPS_SSH:-$HOME/.ssh}"
GUI_PUBLISH="${SSH_OPS_GUI_PUBLISH:-127.0.0.1:8765:8765}"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/pods.log"

# Long-running containers this script (re)starts: "name|mode".
MANAGED=( "ssh-ops-gui|gui" )

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
  mkdir -p "$DATA_DIR"
  case "$mode" in
    gui)
      podman run -d --name "$name" --restart unless-stopped \
        -p "$GUI_PUBLISH" \
        -v "$DATA_DIR:/data" \
        -v "$SSH_DIR:/root/.ssh:ro" \
        "$IMAGE" gui >/dev/null
      ;;
    *) die "unknown container mode '$mode'";;
  esac
  say "(re)started $name"
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
    say "done. Note: the MCP server is relaunched by fully quitting and reopening the desktop app."
    ;;
esac
