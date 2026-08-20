#!/usr/bin/env bash
# Health check for IOS-XE TIG stack (Telegraf + InfluxDB + Grafana).
#
#   bash tests/iosxe-telemetry-ping.sh
set -Eeuo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${CLAWLAB_TELEMETRY_ENV:-$HOME/.clawlab/telemetry/env}"

step() { printf '\n== %s ==\n' "$1"; }
ok() { printf '  OK: %s\n' "$1"; }
fail() { printf '  FAIL: %s\n' "$1"; exit 1; }
warn() { printf '  WARN: %s\n' "$1"; }

step "1) Config"
[[ -f "$ENV_FILE" ]] || fail "missing $ENV_FILE — run admin-access/install-iosxe-telemetry-stack.sh"
# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a
ok "env loaded"
ok "MDT publish=${TELEMETRY_MDT_PUBLISH:-unknown}"

step "2) Podman containers"
if command -v podman >/dev/null 2>&1; then
  for c in iosxe-influxdb iosxe-telegraf iosxe-grafana; do
    if podman ps --format '{{.Names}}' 2>/dev/null | grep -qx "$c"; then
      ok "$c running"
    else
      fail "$c not running — bash iosxe-telemetry/podctl.sh --recreate"
    fi
  done
else
  warn "podman not on PATH — skipping container checks"
fi

step "3) InfluxDB"
code="$(curl -sS -m5 -o /dev/null -w '%{http_code}' http://127.0.0.1:8086/health 2>/dev/null || echo 000)"
[[ "$code" == "200" ]] || fail "InfluxDB /health HTTP $code"
ok "InfluxDB healthy"

if command -v influx >/dev/null 2>&1 && [[ -n "${INFLUX_TOKEN:-}" ]]; then
  if influx query 'buckets()' --host http://127.0.0.1:8086 --org "$INFLUX_ORG" --token "$INFLUX_TOKEN" >/dev/null 2>&1; then
    ok "influx CLI auth OK"
  else
    warn "influx CLI query failed (CLI optional)"
  fi
fi

step "4) Grafana"
gcode="000"
for i in 1 2 3 4 5 6; do
  gcode="$(curl -sS -m5 -o /dev/null -w '%{http_code}' http://127.0.0.1:3000/api/health 2>/dev/null || echo 000)"
  [[ "$gcode" == "200" ]] && break
  sleep 2
done
[[ "$gcode" == "200" ]] || fail "Grafana /api/health HTTP $gcode (podman logs iosxe-grafana)"
ok "Grafana healthy"

step "5) Telegraf MDT port"
hostport="${TELEMETRY_MDT_PUBLISH%%:*}"
[[ "$hostport" == "0.0.0.0" || "$hostport" == "127.0.0.1" ]] && hostport="127.0.0.1"
if python3 -c "import socket,sys; s=socket.socket(); s.settimeout(1); s.connect((sys.argv[1],57000)); s.close()" "$hostport" 2>/dev/null; then
  ok "TCP :57000 accepting on $hostport"
else
  warn "TCP :57000 not open on $hostport yet — check podman logs iosxe-telegraf"
fi

step "6) Recent metrics (optional)"
if [[ -n "${INFLUX_TOKEN:-}" ]]; then
  q='from(bucket:"'"${INFLUX_BUCKET:-iosxe_telemetry}"'") |> range(start: -24h) |> limit(n:1)'
  if command -v influx >/dev/null 2>&1; then
    out="$(influx query "$q" --host http://127.0.0.1:8086 --org "${INFLUX_ORG:-clawlab}" --token "$INFLUX_TOKEN" 2>/dev/null || true)"
    if [[ -n "$out" && "$out" != *"empty"* ]]; then
      ok "metrics present in last 24h"
    else
      warn "no metrics in bucket yet — configure switch MDT subscription to this host:57000"
    fi
  else
    warn "influx CLI not installed — skip data probe"
  fi
fi

printf '\nIOS-XE telemetry ping complete.\n'
