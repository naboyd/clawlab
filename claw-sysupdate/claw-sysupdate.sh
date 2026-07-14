#!/usr/bin/env bash
#
# claw-sysupdate.sh
# ---------------------------------------------------------------------------
# Unattended system updater for Ubuntu/Debian.
#
# Policy (per configuration):
#   * Scope : apply ALL apt updates (full-upgrade), not just security.
#   * Reboot: NEVER reboots. If a reboot is required it is flagged in the
#             status file and (optionally) pushed to a notification webhook,
#             then a human decides.
#
# Runs as root. Driven by claw-sysupdate.timer (systemd) or on demand via:
#     sudo systemctl start claw-sysupdate.service
#
# Environment overrides:
#   CLAW_UPDATE_LOG_DIR   (default /var/log/claw-sysupdate)
#   CLAW_UPDATE_STATE     (default /var/lib/claw-sysupdate/last-run.json)
#   CLAW_UPDATE_WEBHOOK   (optional; POST the JSON summary here)
# ---------------------------------------------------------------------------

set -Eeuo pipefail

LOG_DIR="${CLAW_UPDATE_LOG_DIR:-/var/log/claw-sysupdate}"
STATE_FILE="${CLAW_UPDATE_STATE:-/var/lib/claw-sysupdate/last-run.json}"
NOTIFY_WEBHOOK="${CLAW_UPDATE_WEBHOOK:-}"
export DEBIAN_FRONTEND=noninteractive

if [[ "${EUID}" -ne 0 ]]; then
  echo "claw-sysupdate: must run as root." >&2
  echo "  Trigger it with:  sudo systemctl start claw-sysupdate.service" >&2
  exit 1
fi

ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
mkdir -p "$LOG_DIR" "$(dirname "$STATE_FILE")"
log="$LOG_DIR/update-$(date -u +%Y%m%d-%H%M%S).log"

exec > >(tee -a "$log") 2>&1

echo "== claw-sysupdate ${ts} on $(hostname) =="

apt-get update -o Acquire::Retries=3 -o DPkg::Lock::Timeout=300

mapfile -t upgradable < <(apt-get -s dist-upgrade 2>/dev/null | awk '/^Inst /{print $2}')
count="${#upgradable[@]}"
echo "Upgradable packages: ${count}"
[[ "$count" -gt 0 ]] && printf '  - %s\n' "${upgradable[@]}"

status="ok"
changed=0
if [[ "$count" -gt 0 ]]; then
  if apt-get -y \
       -o Dpkg::Options::=--force-confdef \
       -o Dpkg::Options::=--force-confold \
       -o DPkg::Lock::Timeout=300 full-upgrade; then
    changed=1
  else
    status="upgrade-failed"
  fi
  apt-get -y autoremove --purge || true
  apt-get -y autoclean || true
else
  echo "Nothing to upgrade."
fi

reboot_required=false
reboot_pkgs=""
if [[ -f /var/run/reboot-required ]]; then
  reboot_required=true
  [[ -f /var/run/reboot-required.pkgs ]] && \
    reboot_pkgs="$(paste -sd, /var/run/reboot-required.pkgs 2>/dev/null || true)"
fi

cat > "$STATE_FILE" <<JSON
{
  "timestamp": "${ts}",
  "host": "$(hostname)",
  "status": "${status}",
  "changed": ${changed},
  "upgraded_count": ${count},
  "reboot_required": ${reboot_required},
  "reboot_pkgs": "${reboot_pkgs}",
  "log": "${log}"
}
JSON

echo "--- summary ---"
cat "$STATE_FILE"

if [[ "$reboot_required" == "true" ]]; then
  echo "NOTICE: a reboot is required (${reboot_pkgs:-kernel/libraries})."
  echo "        Not rebooting — per policy a human decides. Reboot with: sudo systemctl reboot"
fi

if [[ -n "$NOTIFY_WEBHOOK" ]]; then
  curl -fsS -X POST -H 'Content-Type: application/json' \
    --data @"$STATE_FILE" "$NOTIFY_WEBHOOK" >/dev/null 2>&1 \
    && echo "notified webhook" || echo "notify failed (non-fatal)"
fi

[[ "$status" == "ok" ]]
