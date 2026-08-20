#!/usr/bin/env bash
# Generate IOS-XE MDT dial-out config for ClawLab TIG (Telegraf :57000).
#
#   bash iosxe-telemetry/scripts/gen-mdt-test-config.sh
#   bash iosxe-telemetry/scripts/gen-mdt-test-config.sh --host 9300-24-Office
#   MDT_COLLECTOR_IP=192.168.128.93 bash iosxe-telemetry/scripts/gen-mdt-test-config.sh --apply
#
# Defaults: collector from ~/.clawlab/telemetry/env (TELEMETRY_MDT_PUBLISH) or icecream LAN.
# Lab transport: grpc-tcp (matches Telegraf without TLS). Use grpc-tls in production.
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
      sed -n '1,12p' "$0" | sed 's/^# \{0,1\}//'
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
PERIOD_MS="${MDT_PERIOD_MS:-5000}"
SOURCE_VRF="${MDT_SOURCE_VRF:-}"
SOURCE_ADDRESS="${MDT_SOURCE_ADDRESS:-}"

vrf_lines() {
  if [[ -n "$SOURCE_VRF" ]]; then
    echo " source-vrf ${SOURCE_VRF}"
  fi
  if [[ -n "$SOURCE_ADDRESS" ]]; then
    echo " source-address ${SOURCE_ADDRESS}"
  fi
}

VRF_BLOCK="$(vrf_lines)"

read -r -d '' CONFIG <<EOF || true
! =============================================================================
! ClawLab MDT test — ${HOST_LABEL} → Telegraf ${COLLECTOR_IP}:${COLLECTOR_PORT}
! Generated: $(date -u +%Y-%m-%dT%H:%MZ)
! Apply: configure terminal → paste → end → write memory
! Verify: show telemetry ietf subscription all
! Rollback: iosxe-telemetry/config/switches/${HOST_LABEL}-mdt-test-rollback.conf
! =============================================================================
!
! Prerequisites: NTP synced (show clock); IP route to ${COLLECTOR_IP}:${COLLECTOR_PORT}
! If using VRF for source, set before generate:
!   MDT_SOURCE_VRF=Mgmt-vrf MDT_SOURCE_ADDRESS=10.x.x.x bash $0

configure terminal
!
! Subscription 601 — CPU utilization (5-second)
telemetry ietf subscription 601
 encoding encode-kvgpb
 filter xpath /process-cpu-ios-xe-oper:cpu-usage/cpu-utilization/five-seconds
 stream yang-push
 update-policy periodic ${PERIOD_MS}
${VRF_BLOCK}
 receiver ip address ${COLLECTOR_IP} ${COLLECTOR_PORT} protocol ${PROTO}
!
! Subscription 602 — memory statistics
telemetry ietf subscription 602
 encoding encode-kvgpb
 filter xpath /memory-ios-xe-oper:memory-statistics/memory-statistic
 stream yang-push
 update-policy periodic ${PERIOD_MS}
${VRF_BLOCK}
 receiver ip address ${COLLECTOR_IP} ${COLLECTOR_PORT} protocol ${PROTO}
!
! Subscription 603 — interface statistics (all interfaces)
telemetry ietf subscription 603
 encoding encode-kvgpb
 filter xpath /interfaces-ios-xe-oper:interfaces/interface
 stream yang-push
 update-policy periodic ${PERIOD_MS}
${VRF_BLOCK}
 receiver ip address ${COLLECTOR_IP} ${COLLECTOR_PORT} protocol ${PROTO}
!
end
!
! --- verification (exec mode) ---
! show telemetry ietf subscription all
! show telemetry ietf subscription 601
! show telemetry ietf subscription 602
! show telemetry ietf subscription 603
!
! On icecream after ~1 min:
!   bash tests/iosxe-telemetry-ping.sh
!   source ~/.clawlab/telemetry/env
!   podman logs --tail 30 iosxe-telegraf
EOF

OUT_DIR="$REPO/iosxe-telemetry/config/switches"
OUT_FILE="$OUT_DIR/${HOST_LABEL}-mdt-test.generated.conf"
mkdir -p "$OUT_DIR"
printf '%s\n' "$CONFIG" > "$OUT_FILE"

echo "Wrote $OUT_FILE"
echo "  collector: ${COLLECTOR_IP}:${COLLECTOR_PORT} protocol ${PROTO}"
echo "  period:    ${PERIOD_MS} ms"

if [[ "$APPLY" -eq 1 || "$DRY_RUN" -eq 1 ]]; then
  SSH_HOST="${MDT_SSH_HOST:-$HOST_LABEL}"
  DATA="${SSH_OPS_DATA:-$HOME/.clawlab/ssh-ops/data}"
  HOSTS="${SSH_OPS_CONFIG:-$DATA/hosts.yaml}"
  if [[ ! -f "$HOSTS" ]]; then
    echo "error: no ssh-ops hosts.yaml — apply manually or add ${HOST_LABEL} to MCP Admin" >&2
    exit 1
  fi
  TARGET="$(python3 - "$HOSTS" "$SSH_HOST" <<'PY'
import sys
try:
    import yaml
except ImportError:
    raise SystemExit("")
p, name = sys.argv[1], sys.argv[2]
cfg = yaml.safe_load(open(p)) or {}
h = (cfg.get("hosts") or {}).get(name)
if not h:
    raise SystemExit("")
print(h.get("hostname") or name)
PY
)"
  if [[ -z "$TARGET" ]]; then
    echo "error: host '${SSH_HOST}' not in $HOSTS" >&2
    exit 1
  fi
  echo "Target: ${SSH_HOST} (${TARGET})"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "Dry run — config not pushed. Paste $OUT_FILE on the switch."
    exit 0
  fi
  echo "Pushing config via SSH (enable required on switch)..."
  ssh -o BatchMode=yes -o ConnectTimeout=10 "$TARGET" <<SSHEOF
configure terminal
$(grep -v '^!' "$OUT_FILE" | grep -v '^$' | grep -v '^end$' | grep -v '^configure terminal$')
end
write memory
SSHEOF
  echo "Done. Verify: show telemetry ietf subscription all"
fi
