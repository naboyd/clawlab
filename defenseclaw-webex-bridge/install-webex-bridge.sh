#!/usr/bin/env bash
# install-webex-bridge.sh — deploy the DefenseClaw audit->Webex bridge as a
# rootless systemd *user* service (no sudo required). Idempotent.
set -Eeuo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/.defenseclaw/webex-bridge"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT="dc-webex-bridge.service"

echo "==> Installing bridge to $DEST"
install -d -m 0755 "$DEST"
install -m 0755 "$SRC/dc-webex-bridge.py" "$DEST/dc-webex-bridge.py"
install -m 0644 "$SRC/README.md"          "$DEST/README.md" 2>/dev/null || true

echo "==> Checking python3 + pyyaml"
python3 -c 'import yaml' 2>/dev/null || { echo "ERROR: python3 pyyaml missing"; exit 1; }

echo "==> Dry-check config discovery"
python3 "$DEST/dc-webex-bridge.py" --test >/tmp/dc-bridge-test.log 2>&1 || {
  echo "WARN: --test dispatch failed; see /tmp/dc-bridge-test.log"; cat /tmp/dc-bridge-test.log; }

echo "==> Installing systemd user unit -> $UNIT_DIR/$UNIT"
install -d -m 0755 "$UNIT_DIR"
install -m 0644 "$SRC/$UNIT" "$UNIT_DIR/$UNIT"

echo "==> Enabling linger so the service runs without an active login session"
loginctl enable-linger "$USER" 2>/dev/null || true

echo "==> Reload + enable + start"
systemctl --user daemon-reload
systemctl --user enable --now "$UNIT"
sleep 1
systemctl --user --no-pager --lines=8 status "$UNIT" || true

cat <<EOF

Done. The bridge is watching ~/.defenseclaw/audit.db and will post HIGH/CRITICAL
violations to your Webex space.

  Logs:     journalctl --user -u dc-webex-bridge -f
  State:    ~/.defenseclaw/webex-bridge.state   (cursor + de-dup set)
  Test:     python3 $DEST/dc-webex-bridge.py --test
  Stop:     systemctl --user stop dc-webex-bridge
EOF
