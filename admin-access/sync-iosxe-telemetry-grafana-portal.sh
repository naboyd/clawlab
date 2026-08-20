#!/usr/bin/env bash
# Align Grafana publish URL and subpath settings with claw-portals config.
#
#   bash admin-access/sync-iosxe-telemetry-grafana-portal.sh
#   bash admin-access/sync-iosxe-telemetry-grafana-portal.sh --no-restart
set -Eeuo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DATA_ROOT="${CLAWLAB_TELEMETRY_DATA:-$HOME/.clawlab/telemetry}"
ENV_FILE="${CLAWLAB_TELEMETRY_ENV:-$DATA_ROOT/env}"
PORTAL_ENV="${CLAW_PORTAL_ENV:-$HOME/.claw-portals/config.env}"
NO_RESTART=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-restart) NO_RESTART=1 ;;
    -h|--help)
      sed -n '1,8p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
  shift
done

[[ -f "$ENV_FILE" ]] || {
  echo "skip: no telemetry stack ($ENV_FILE) — run install-iosxe-telemetry-stack.sh first"
  exit 0
}

LAN_IP="${LAN_IP:-127.0.0.1}"
DOMAIN="${DOMAIN:-lab-host}"
PORT_PORTAL="${PORT_PORTAL:-8443}"
TLS_MODE="${TLS_MODE:-https-le}"
if [[ -f "$PORTAL_ENV" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$PORTAL_ENV"
  set +a
fi

scheme="https"
[[ "$TLS_MODE" == "http" ]] && scheme="http"

GRAFANA_ROOT_URL="${scheme}://${DOMAIN}:${PORT_PORTAL}/grafana/"
TELEMETRY_GRAFANA_PUBLISH="${LAN_IP}:3000:3000"
GRAFANA_PROXY_URL="http://${LAN_IP}:3000"

python3 - "$ENV_FILE" "$GRAFANA_ROOT_URL" "$TELEMETRY_GRAFANA_PUBLISH" "$GRAFANA_PROXY_URL" <<'PY'
import sys
from pathlib import Path

p = Path(sys.argv[1])
root_url, publish, proxy = sys.argv[2], sys.argv[3], sys.argv[4]
keys = {
    "GRAFANA_ROOT_URL": root_url,
    "TELEMETRY_GRAFANA_PUBLISH": publish,
    "GRAFANA_PROXY_URL": proxy,
}
lines = p.read_text().splitlines()
out = []
seen = set()
for line in lines:
    key = line.split("=", 1)[0] if "=" in line else ""
    if key in keys:
        out.append(f"{key}={keys[key]}")
        seen.add(key)
    else:
        out.append(line)
for key, val in keys.items():
    if key not in seen:
        out.append(f"{key}={val}")
p.write_text("\n".join(out).rstrip() + "\n")
PY

echo "Updated Grafana portal settings in $ENV_FILE"
echo "  GRAFANA_ROOT_URL=$GRAFANA_ROOT_URL"
echo "  TELEMETRY_GRAFANA_PUBLISH=$TELEMETRY_GRAFANA_PUBLISH"

if [[ "$NO_RESTART" -eq 0 ]] && command -v podman >/dev/null 2>&1 \
  && podman ps --format '{{.Names}}' 2>/dev/null | grep -qx iosxe-grafana; then
  bash "$REPO/iosxe-telemetry/podctl.sh" --recreate-grafana
fi
