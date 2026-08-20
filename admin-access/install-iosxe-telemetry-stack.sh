#!/usr/bin/env bash
# Install IOS-XE TIG stack (Telegraf MDT + InfluxDB + Grafana) via Podman.
#
# Secrets and rendered configs live under ~/.clawlab/telemetry/ (not git).
# Splunk is not used for MDT — syslog alerts remain on existing Splunk path.
#
#   bash admin-access/install-iosxe-telemetry-stack.sh
#   bash admin-access/install-iosxe-telemetry-stack.sh --no-start
set -Eeuo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DATA_ROOT="${CLAWLAB_TELEMETRY_DATA:-$HOME/.clawlab/telemetry}"
ENV_FILE="${CLAWLAB_TELEMETRY_ENV:-$DATA_ROOT/env}"
PORTAL_ENV="${CLAW_PORTAL_ENV:-$HOME/.claw-portals/config.env}"
NO_START=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-start) NO_START=1 ;;
    -h|--help)
      sed -n '1,12p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
  shift
done

say() { printf '>> %s\n' "$*"; }

gen_secret() {
  python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
}

mkdir -p "$DATA_ROOT/telegraf" "$DATA_ROOT/grafana/provisioning/datasources" \
  "$DATA_ROOT/influx/data" "$DATA_ROOT/influx/config" "$DATA_ROOT/grafana/data"

if [[ ! -f "$ENV_FILE" ]]; then
  say "Creating $ENV_FILE from template"
  cp "$REPO/config-templates/iosxe-telemetry.env.example" "$ENV_FILE"
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  INFLUX_TOKEN="$(gen_secret)"
  INFLUX_ADMIN_PASSWORD="$(gen_secret)"
  GRAFANA_ADMIN_PASSWORD="$(gen_secret)"
  {
    grep -v '^INFLUX_TOKEN=' "$ENV_FILE" | grep -v '^INFLUX_ADMIN_PASSWORD=' | grep -v '^GRAFANA_ADMIN_PASSWORD='
    printf 'INFLUX_TOKEN=%s\n' "$INFLUX_TOKEN"
    printf 'INFLUX_ADMIN_PASSWORD=%s\n' "$INFLUX_ADMIN_PASSWORD"
    printf 'GRAFANA_ADMIN_PASSWORD=%s\n' "$GRAFANA_ADMIN_PASSWORD"
  } > "${ENV_FILE}.tmp"
  mv "${ENV_FILE}.tmp" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
else
  say "Using existing $ENV_FILE"
  # shellcheck disable=SC1090
  source "$ENV_FILE"
fi

LAN_IP=""
if [[ -f "$PORTAL_ENV" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$PORTAL_ENV"
  set +a
  LAN_IP="${LAN_IP:-}"
fi

if [[ -n "$LAN_IP" && "$LAN_IP" != "127.0.0.1" ]]; then
  MDT_PUBLISH="${LAN_IP}:57000:57000"
else
  MDT_PUBLISH="0.0.0.0:57000:57000"
fi

if grep -q '^TELEMETRY_MDT_PUBLISH=' "$ENV_FILE"; then
  python3 - "$ENV_FILE" "$MDT_PUBLISH" <<'PY'
import sys
from pathlib import Path
p, val = Path(sys.argv[1]), sys.argv[2]
lines = p.read_text().splitlines()
out = []
for line in lines:
    if line.startswith("TELEMETRY_MDT_PUBLISH="):
        out.append(f"TELEMETRY_MDT_PUBLISH={val}")
    else:
        out.append(line)
p.write_text("\n".join(out) + "\n")
PY
else
  printf 'TELEMETRY_MDT_PUBLISH=%s\n' "$MDT_PUBLISH" >> "$ENV_FILE"
fi
chmod 600 "$ENV_FILE"

# shellcheck disable=SC1090
source "$ENV_FILE"

say "Installing Telegraf config"
cp "$REPO/iosxe-telemetry/config/telegraf.conf" "$DATA_ROOT/telegraf/telegraf.conf"
chmod 644 "$DATA_ROOT/telegraf/telegraf.conf"

say "Rendering Grafana Influx datasource"
python3 - "$REPO" "$DATA_ROOT" "$INFLUX_TOKEN" <<'PY'
import sys
from pathlib import Path
repo, root, token = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
src = repo / "iosxe-telemetry/config/grafana/provisioning/datasources/influx.yaml.template"
dst = root / "grafana/provisioning/datasources/influx.yaml"
dst.write_text(src.read_text().replace("@INFLUX_TOKEN@", token))
dst.chmod(0o600)
PY

chmod +x "$REPO/iosxe-telemetry/podctl.sh"

bash "$REPO/admin-access/install-clawlab-skills.sh" >/dev/null 2>&1 || true

if [[ "$NO_START" -eq 0 ]]; then
  say "Starting TIG stack"
  bash "$REPO/iosxe-telemetry/podctl.sh" --recreate
fi

echo ""
echo "IOS-XE telemetry stack installed."
echo "  env:      $ENV_FILE"
echo "  MDT:      $MDT_PUBLISH (configure switch subscriptions to this host:57000)"
echo "  Influx:   http://127.0.0.1:8086  org=$INFLUX_ORG bucket=$INFLUX_BUCKET"
echo "  Grafana:  http://127.0.0.1:3000/  user=${GRAFANA_ADMIN_USER:-admin}"
echo "  verify:   bash $REPO/tests/iosxe-telemetry-ping.sh"
echo "  docs:     $REPO/iosxe-telemetry/README.md"
