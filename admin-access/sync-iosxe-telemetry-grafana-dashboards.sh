#!/usr/bin/env bash
# Copy provisioned Grafana dashboards/datasource from repo → ~/.clawlab/telemetry and restart Grafana.
#
#   bash admin-access/sync-iosxe-telemetry-grafana-dashboards.sh
#   bash admin-access/sync-iosxe-telemetry-grafana-dashboards.sh --no-restart
set -Eeuo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DATA_ROOT="${CLAWLAB_TELEMETRY_DATA:-$HOME/.clawlab/telemetry}"
ENV_FILE="${CLAWLAB_TELEMETRY_ENV:-$DATA_ROOT/env}"
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

[[ -f "$ENV_FILE" ]] || { echo "missing $ENV_FILE" >&2; exit 1; }
# shellcheck disable=SC1090
source "$ENV_FILE"

mkdir -p "$DATA_ROOT/grafana/dashboards" "$DATA_ROOT/grafana/provisioning/dashboards" \
  "$DATA_ROOT/grafana/provisioning/datasources"

cp "$REPO/iosxe-telemetry/config/grafana/provisioning/dashboards/default.yaml" \
  "$DATA_ROOT/grafana/provisioning/dashboards/default.yaml"
cp "$REPO/iosxe-telemetry/config/grafana/dashboards/"*.json "$DATA_ROOT/grafana/dashboards/"
chmod 644 "$DATA_ROOT/grafana/provisioning/dashboards/default.yaml" "$DATA_ROOT/grafana/dashboards/"*.json

python3 - "$REPO" "$DATA_ROOT" "$INFLUX_TOKEN" <<'PY'
import sys
from pathlib import Path
repo, root, token = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
src = repo / "iosxe-telemetry/config/grafana/provisioning/datasources/influx.yaml.template"
dst = root / "grafana/provisioning/datasources/influx.yaml"
dst.write_text(src.read_text().replace("@INFLUX_TOKEN@", token))
dst.chmod(0o644)
PY

echo "Synced Grafana dashboards to $DATA_ROOT/grafana/dashboards"

if [[ "$NO_RESTART" -eq 0 ]]; then
  bash "$REPO/iosxe-telemetry/podctl.sh" --recreate-grafana
fi

echo "Dashboard: IOS-XE Telemetry → IOS-XE MDT — Catalyst Office"
