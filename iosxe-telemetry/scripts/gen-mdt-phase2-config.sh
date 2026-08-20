#!/usr/bin/env bash
# Generate IOS-XE MDT phase-2 config (604–608 + tune 603) for ClawLab TIG.
#
#   bash iosxe-telemetry/scripts/gen-mdt-phase2-config.sh
#   bash iosxe-telemetry/scripts/gen-mdt-phase2-config.sh --host 9300-24-Office --apply
set -Eeuo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
PORTAL_ENV="${CLAW_PORTAL_ENV:-$HOME/.claw-portals/config.env}"
TELEMETRY_ENV="${CLAWLAB_TELEMETRY_ENV:-$HOME/.clawlab/telemetry/env}"
HOST_LABEL="${MDT_SWITCH_NAME:-9300-24-Office}"
APPLY=0
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST_LABEL="$2"; shift 2 ;;
    --apply) APPLY=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help)
      sed -n '1,8p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

default_collector_ip() {
  if [[ -n "${MDT_COLLECTOR_IP:-}" ]]; then
    printf '%s' "$MDT_COLLECTOR_IP"
    return
  fi
  if [[ -f "$TELEMETRY_ENV" ]]; then
    # shellcheck disable=SC1090
    source "$TELEMETRY_ENV"
    local pub="${TELEMETRY_MDT_PUBLISH:-}"
    if [[ -n "$pub" ]]; then
      printf '%s' "${pub%%:*}"
      return
    fi
  fi
  if [[ -f "$PORTAL_ENV" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$PORTAL_ENV"
    set +a
    if [[ -n "${LAN_IP:-}" ]]; then
      printf '%s' "$LAN_IP"
      return
    fi
  fi
  printf '%s' "192.168.128.93"
}

COLLECTOR_IP="$(default_collector_ip)"
COLLECTOR_PORT="${MDT_COLLECTOR_PORT:-57000}"
PROTO="${MDT_PROTOCOL:-grpc-tcp}"
SOURCE_VRF="${MDT_SOURCE_VRF:-}"
SOURCE_ADDRESS="${MDT_SOURCE_ADDRESS:-}"

vrf_lines() {
  if [[ -n "$SOURCE_VRF" ]]; then echo " source-vrf ${SOURCE_VRF}"; fi
  if [[ -n "$SOURCE_ADDRESS" ]]; then echo " source-address ${SOURCE_ADDRESS}"; fi
}
VRF_BLOCK="$(vrf_lines)"

read -r -d '' CONFIG <<EOF || true
! ClawLab MDT phase 2 — ${HOST_LABEL} → Telegraf ${COLLECTOR_IP}:${COLLECTOR_PORT}
! Generated: $(date -u +%Y-%m-%dT%H:%MZ)

configure terminal
!
telemetry ietf subscription 603
 update-policy periodic 30000
!
telemetry ietf subscription 604
 encoding encode-kvgpb
 filter xpath /platform-ios-xe-oper:components/component
 stream yang-push
 update-policy periodic 30000
${VRF_BLOCK}
 receiver ip address ${COLLECTOR_IP} ${COLLECTOR_PORT} protocol ${PROTO}
!
telemetry ietf subscription 605
 encoding encode-kvgpb
 filter xpath /environment-ios-xe-oper:environment-sensors/environment-sensor
 stream yang-push
 update-policy periodic 30000
${VRF_BLOCK}
 receiver ip address ${COLLECTOR_IP} ${COLLECTOR_PORT} protocol ${PROTO}
!
telemetry ietf subscription 606
 encoding encode-kvgpb
 filter xpath /poe-ios-xe-oper:poe-port-detail
 stream yang-push
 update-policy periodic 30000
${VRF_BLOCK}
 receiver ip address ${COLLECTOR_IP} ${COLLECTOR_PORT} protocol ${PROTO}
!
telemetry ietf subscription 607
 encoding encode-kvgpb
 filter xpath /lldp-ios-xe-oper:lldp-nbrs/lldp-nbr
 stream yang-push
 update-policy periodic 60000
${VRF_BLOCK}
 receiver ip address ${COLLECTOR_IP} ${COLLECTOR_PORT} protocol ${PROTO}
!
telemetry ietf subscription 608
 encoding encode-kvgpb
 filter xpath /spanning-tree-ios-xe-oper:spanning-tree-oper-data
 stream yang-push
 update-policy periodic 30000
${VRF_BLOCK}
 receiver ip address ${COLLECTOR_IP} ${COLLECTOR_PORT} protocol ${PROTO}
!
end
write memory
EOF

OUT_DIR="$REPO/iosxe-telemetry/config/switches"
OUT_FILE="$OUT_DIR/${HOST_LABEL}-mdt-phase2.generated.conf"
mkdir -p "$OUT_DIR"
printf '%s\n' "$CONFIG" > "$OUT_FILE"

echo "Wrote $OUT_FILE"
echo "  collector: ${COLLECTOR_IP}:${COLLECTOR_PORT} protocol ${PROTO}"

if [[ "$APPLY" -eq 1 || "$DRY_RUN" -eq 1 ]]; then
  SSH_HOST="${MDT_SSH_HOST:-$HOST_LABEL}"
  DATA="${SSH_OPS_DATA:-$HOME/.clawlab/ssh-ops/data}"
  HOSTS="${SSH_OPS_CONFIG:-$DATA/hosts.yaml}"
  if [[ ! -f "$HOSTS" ]]; then
    echo "error: no ssh-ops hosts.yaml — paste $OUT_FILE manually" >&2
    exit 1
  fi
  TARGET="$(python3 - "$HOSTS" "$SSH_HOST" <<'PY'
import sys
try:
    import yaml
except ImportError:
    raise SystemExit("")
cfg = yaml.safe_load(open(sys.argv[1])) or {}
h = (cfg.get("hosts") or {}).get(sys.argv[2])
if not h:
    raise SystemExit("")
print(h.get("hostname") or sys.argv[2])
PY
)"
  if [[ -z "$TARGET" ]]; then
    echo "error: host '${SSH_HOST}' not in $HOSTS" >&2
    exit 1
  fi
  echo "Target: ${SSH_HOST} (${TARGET})"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "Dry run — config not pushed."
    exit 0
  fi
  ssh -o BatchMode=yes -o ConnectTimeout=10 "$TARGET" <<SSHEOF
configure terminal
$(grep -v '^!' "$OUT_FILE" | grep -v '^$' | grep -v '^end$' | grep -v '^configure terminal$' | grep -v '^write memory$')
end
write memory
SSHEOF
  echo "Done. Verify: show telemetry ietf subscription all"
fi
