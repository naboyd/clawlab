#!/usr/bin/env bash
# install-claw-sysupdate.sh — install the claw system updater + systemd timer.
#     sudo ./install-claw-sysupdate.sh
set -Eeuo pipefail
if [[ "${EUID}" -ne 0 ]]; then echo "Run as root: sudo $0" >&2; exit 1; fi
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
SBIN=/usr/local/sbin/claw-sysupdate.sh
UNIT_DIR=/etc/systemd/system
echo "==> Installing updater script -> ${SBIN}"
install -m 0755 "${SRC_DIR}/claw-sysupdate.sh" "${SBIN}"
echo "==> Installing systemd units -> ${UNIT_DIR}"
install -m 0644 "${SRC_DIR}/claw-sysupdate.service" "${UNIT_DIR}/claw-sysupdate.service"
install -m 0644 "${SRC_DIR}/claw-sysupdate.timer"   "${UNIT_DIR}/claw-sysupdate.timer"
echo "==> Creating state/log directories"
install -d -m 0755 /var/log/claw-sysupdate /var/lib/claw-sysupdate
echo "==> Enabling timer"
systemctl daemon-reload
systemctl enable --now claw-sysupdate.timer
echo ""
echo "Installed. Next scheduled run:"
systemctl list-timers claw-sysupdate.timer --no-pager || true
echo ""
echo "Run once now:      sudo systemctl start claw-sysupdate.service"
echo "Watch it:          journalctl -u claw-sysupdate -f"
echo "Last-run summary:  cat /var/lib/claw-sysupdate/last-run.json"
