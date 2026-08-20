#!/usr/bin/env bash
#
# podctl.sh — Podman lifecycle for IOS-XE TIG stack (Telegraf + InfluxDB + Grafana).
#
#   ./podctl.sh                 ensure containers are up
#   ./podctl.sh --recreate      remove and recreate all
#   ./podctl.sh --stop          stop and remove containers
#   ./podctl.sh --status        print status
#   ./podctl.sh --logs [name]   tail logs (telegraf|influx|grafana|all)
#
set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$_SCRIPT_DIR/.." && pwd)"
DATA_ROOT="${CLAWLAB_TELEMETRY_DATA:-$HOME/.clawlab/telemetry}"
ENV_FILE="${CLAWLAB_TELEMETRY_ENV:-$DATA_ROOT/env}"
NETWORK="${CLAWLAB_TELEMETRY_NETWORK:-clawlab-telemetry}"
PORTAL_ENV="${CLAW_PORTAL_ENV:-$HOME/.claw-portals/config.env}"

INFLUX_NAME=iosxe-influxdb
TELEGRAF_NAME=iosxe-telegraf
GRAFANA_NAME=iosxe-grafana

say() { printf '>> %s\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*" >&2; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

usage() { sed -n '3,12p' "$0" | sed 's/^# \{0,1\}//'; }

need_podman() { command -v podman >/dev/null 2>&1 || die "podman not found"; }

load_env() {
  [[ -f "$ENV_FILE" ]] || die "missing $ENV_FILE — run: bash $REPO/admin-access/install-iosxe-telemetry-stack.sh"
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
  : "${INFLUX_ORG:=clawlab}"
  : "${INFLUX_BUCKET:=iosxe_telemetry}"
  : "${INFLUX_URL:=http://iosxe-influxdb:8086}"
  : "${INFLUX_IMAGE:=docker.io/library/influxdb:2.7-alpine}"
  : "${TELEGRAF_IMAGE:=docker.io/library/telegraf:1.32-alpine}"
  : "${GRAFANA_IMAGE:=docker.io/grafana/grafana:11.4.0}"
  : "${TELEMETRY_MDT_PUBLISH:=0.0.0.0:57000:57000}"
  : "${TELEMETRY_GRAFANA_PUBLISH:=127.0.0.1:3000:3000}"
  : "${GRAFANA_ROOT_URL:=http://127.0.0.1:3000/}"
  : "${GRAFANA_PROXY_URL:=http://127.0.0.1:3000}"
  [[ -n "${INFLUX_TOKEN:-}" ]] || die "INFLUX_TOKEN empty in $ENV_FILE"
  [[ -n "${GRAFANA_ADMIN_PASSWORD:-}" ]] || die "GRAFANA_ADMIN_PASSWORD empty in $ENV_FILE"
}

ensure_network() {
  podman network exists "$NETWORK" 2>/dev/null || podman network create "$NETWORK" >/dev/null
}

is_running() { podman ps --format '{{.Names}}' 2>/dev/null | grep -qx "$1"; }

wait_influx() {
  local i=0
  while [[ "$i" -lt 60 ]]; do
    if curl -sf -m2 "http://127.0.0.1:8086/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
    i=$((i + 1))
  done
  return 1
}

start_influx() {
  local init_mode=none
  [[ -d "$DATA_ROOT/influx/data" && -n "$(ls -A "$DATA_ROOT/influx/data" 2>/dev/null)" ]] || init_mode=setup

  podman rm -f "$INFLUX_NAME" >/dev/null 2>&1 || true
  mkdir -p "$DATA_ROOT/influx/data" "$DATA_ROOT/influx/config"

  local -a init_env=()
  if [[ "$init_mode" == "setup" ]]; then
    say "InfluxDB first-time setup (org=$INFLUX_ORG bucket=$INFLUX_BUCKET)"
    init_env=(
      -e "DOCKER_INFLUXDB_INIT_MODE=setup"
      -e "DOCKER_INFLUXDB_INIT_USERNAME=${INFLUX_ADMIN_USER:-admin}"
      -e "DOCKER_INFLUXDB_INIT_PASSWORD=${INFLUX_ADMIN_PASSWORD}"
      -e "DOCKER_INFLUXDB_INIT_ORG=${INFLUX_ORG}"
      -e "DOCKER_INFLUXDB_INIT_BUCKET=${INFLUX_BUCKET}"
      -e "DOCKER_INFLUXDB_INIT_ADMIN_TOKEN=${INFLUX_TOKEN}"
    )
  else
    init_env=(-e DOCKER_INFLUXDB_INIT_MODE=none)
  fi

  podman run -d --name "$INFLUX_NAME" --restart unless-stopped \
    --network "$NETWORK" --network-alias iosxe-influxdb \
    -p "127.0.0.1:8086:8086" \
    "${init_env[@]}" \
    -v "$DATA_ROOT/influx/data:/var/lib/influxdb2:Z" \
    -v "$DATA_ROOT/influx/config:/etc/influxdb2:Z" \
    "$INFLUX_IMAGE" >/dev/null

  say "waiting for InfluxDB health..."
  wait_influx || die "InfluxDB did not become healthy — podman logs $INFLUX_NAME"
  say "started $INFLUX_NAME"
}

start_telegraf() {
  local conf="$DATA_ROOT/telegraf/telegraf.conf"
  [[ -f "$conf" ]] || die "missing $conf — re-run install-iosxe-telemetry-stack.sh"

  podman rm -f "$TELEGRAF_NAME" >/dev/null 2>&1 || true
  podman run -d --name "$TELEGRAF_NAME" --restart unless-stopped \
    --network "$NETWORK" \
    -p "$TELEMETRY_MDT_PUBLISH" \
    --env-file "$ENV_FILE" \
    --user 0:0 \
    --entrypoint /usr/bin/telegraf \
    -v "$conf:/etc/telegraf/telegraf.conf:ro,Z" \
    "$TELEGRAF_IMAGE" --config /etc/telegraf/telegraf.conf >/dev/null
  say "started $TELEGRAF_NAME (MDT publish $TELEMETRY_MDT_PUBLISH)"
}

start_grafana() {
  local prov="$DATA_ROOT/grafana/provisioning"
  [[ -d "$prov" ]] || die "missing $prov — re-run install-iosxe-telemetry-stack.sh"

  podman rm -f "$GRAFANA_NAME" >/dev/null 2>&1 || true
  mkdir -p "$DATA_ROOT/grafana/data"
  podman run -d --name "$GRAFANA_NAME" --restart unless-stopped \
    --network "$NETWORK" \
    -p "$TELEMETRY_GRAFANA_PUBLISH" \
    -e "GF_SECURITY_ADMIN_USER=${GRAFANA_ADMIN_USER:-admin}" \
    -e "GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD}" \
    -e GF_USERS_ALLOW_SIGN_UP=false \
    -e "GF_SERVER_ROOT_URL=${GRAFANA_ROOT_URL}" \
    -e GF_SERVER_SERVE_FROM_SUB_PATH=true \
    -e GF_SECURITY_COOKIE_SAMESITE=lax \
    -e GF_SECURITY_ALLOW_EMBEDDING=true \
    -v "$DATA_ROOT/grafana/data:/var/lib/grafana:Z" \
    -v "$prov:/etc/grafana/provisioning:ro,Z" \
    "$GRAFANA_IMAGE" >/dev/null
  say "started $GRAFANA_NAME (${GRAFANA_ROOT_URL} publish ${TELEMETRY_GRAFANA_PUBLISH})"
}

ensure_up() {
  load_env
  ensure_network
  if is_running "$INFLUX_NAME"; then say "$INFLUX_NAME already running"; else start_influx; fi
  if is_running "$TELEGRAF_NAME"; then say "$TELEGRAF_NAME already running"; else start_telegraf; fi
  if is_running "$GRAFANA_NAME"; then say "$GRAFANA_NAME already running"; else start_grafana; fi
}

recreate_all() {
  load_env
  ensure_network
  start_influx
  start_telegraf
  start_grafana
}

stop_all() {
  for c in "$GRAFANA_NAME" "$TELEGRAF_NAME" "$INFLUX_NAME"; do
    podman rm -f "$c" >/dev/null 2>&1 || true
    say "removed $c"
  done
}

show_status() {
  load_env 2>/dev/null || true
  printf 'env: %s\n' "$ENV_FILE"
  printf 'network: %s\n' "$NETWORK"
  podman ps -a --filter "name=iosxe-" --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null || true
  if curl -sf -m2 http://127.0.0.1:8086/health >/dev/null 2>&1; then
    say "InfluxDB /health OK"
  else
    warn "InfluxDB not reachable on 127.0.0.1:8086"
  fi
  local grafana_check="${GRAFANA_PROXY_URL:-http://127.0.0.1:3000}"
  if curl -sf -m2 "${grafana_check}/api/health" >/dev/null 2>&1; then
    say "Grafana /api/health OK ($grafana_check)"
  else
    warn "Grafana not reachable at $grafana_check"
  fi
}

show_logs() {
  local target="${1:-all}"
  case "$target" in
    telegraf) podman logs --tail 80 "$TELEGRAF_NAME" 2>&1 ;;
    influx|influxdb) podman logs --tail 80 "$INFLUX_NAME" 2>&1 ;;
    grafana) podman logs --tail 80 "$GRAFANA_NAME" 2>&1 ;;
    all)
      for c in "$INFLUX_NAME" "$TELEGRAF_NAME" "$GRAFANA_NAME"; do
        echo "=== $c ==="
        podman logs --tail 40 "$c" 2>&1 || true
      done
      ;;
    *) die "unknown log target: $target (telegraf|influx|grafana|all)" ;;
  esac
}

recreate_grafana() {
  load_env
  ensure_network
  start_grafana
}

# ---- main -----------------------------------------------------------------
need_podman
ACTION=ensure
LOG_TARGET=all
while [[ $# -gt 0 ]]; do
  case "$1" in
    --recreate) ACTION=recreate ;;
    --recreate-grafana) ACTION=recreate-grafana ;;
    --stop) ACTION=stop ;;
    --status) ACTION=status ;;
    --logs) ACTION=logs; shift; LOG_TARGET="${1:-all}"; break ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
  shift
done

case "$ACTION" in
  ensure) ensure_up ;;
  recreate) recreate_all ;;
  recreate-grafana) recreate_grafana ;;
  stop) stop_all ;;
  status) show_status ;;
  logs) show_logs "$LOG_TARGET" ;;
esac

say "done"
