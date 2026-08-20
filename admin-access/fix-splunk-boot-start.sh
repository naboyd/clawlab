#!/usr/bin/env bash
# Re-enable Splunk after a major .deb upgrade (10.x refuses init.d start as root).
# Run on the Splunk host as an admin user with sudo:
#
#   sudo bash admin-access/fix-splunk-boot-start.sh
#
# Or via ssh-ops after setup-sshops-mcp-auth.sh grants SSHOPS_SPLUNK / SSHOPS_SPLUNK_USER.
set -euo pipefail

SPLUNK=/opt/splunk/bin/splunk

[[ -x "$SPLUNK" ]] || { echo "error: $SPLUNK not found" >&2; exit 1; }
id splunk >/dev/null 2>&1 || { echo "error: splunk OS user missing" >&2; exit 1; }

echo "==> Stop legacy sysv splunk.service (root init.d — fails on Splunk 10.x)"
systemctl stop splunk.service 2>/dev/null || true
systemctl disable splunk.service 2>/dev/null || true

echo "==> Disable legacy init.d boot-start (required before systemd-managed boot-start)"
"$SPLUNK" disable boot-start --accept-license --answer-yes --no-prompt 2>/dev/null || true
systemctl daemon-reload

echo "==> First-time run (ftr) as splunk user (required before boot-start on 10.x)"
sudo -u splunk "$SPLUNK" ftr --accept-license --answer-yes --no-prompt

echo "==> Splunk boot-start as user splunk (systemd-managed)"
"$SPLUNK" enable boot-start -user splunk -systemd-managed 1 --accept-license --answer-yes --no-prompt

systemctl daemon-reload

UNIT=""
for candidate in Splunkd.service splunkd.service; do
  if systemctl list-unit-files "$candidate" 2>/dev/null | grep -q "$candidate"; then
    UNIT="$candidate"
    break
  fi
done

if [[ -n "$UNIT" ]]; then
  echo "==> Enable and start $UNIT"
  systemctl enable "$UNIT"
  systemctl start "$UNIT"
else
  echo "==> Start Splunk as splunk user (no systemd unit yet)"
  sudo -u splunk "$SPLUNK" start --accept-license --answer-yes --no-prompt
fi

sleep 5
sudo -u splunk "$SPLUNK" status || true
systemctl is-active Splunkd.service 2>/dev/null || true
echo "Note: run status as splunk user (SPLUNK_OS_USER=splunk): sudo -u splunk $SPLUNK status"
dpkg -l splunk 2>/dev/null | awk '/^ii/ {print "package:", $2, $3}'
