#!/usr/bin/env bash
# Install daily IOS config archive + drift detection (systemd user timer on icecream).
set -Eeuo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_DIR="${HOME}/.config/systemd/user"
DATA_DIR="${SSH_OPS_DATA:-${HOME}/.clawlab/ssh-ops/data}"
VENV_PY="${CLAW_PYTHON:-${HOME}/.clawlab/venv/bin/python3}"

say() { printf '>> %s\n' "$*"; }

[[ -x "$VENV_PY" ]] || {
  echo "error: missing venv python at $VENV_PY" >&2
  exit 1
}

install -d -m 0755 "$UNIT_DIR"
install -m 0644 "$REPO/systemd-user/ios-config-archive.service" "$UNIT_DIR/"
install -m 0644 "$REPO/systemd-user/ios-config-archive.timer" "$UNIT_DIR/"

# Patch %h paths if repo or venv live elsewhere.
sed -i "s|%h/clawlab|$REPO|g" "$UNIT_DIR/ios-config-archive.service"
sed -i "s|%h/.clawlab/venv/bin/python3|$VENV_PY|g" "$UNIT_DIR/ios-config-archive.service"

mkdir -p "$DATA_DIR/ios-config-archive" "$DATA_DIR/changes"
chmod 700 "$DATA_DIR/ios-config-archive" 2>/dev/null || true

chmod +x "$REPO/ssh-ops-mcp/scripts/ios-config-drift-check.py"

systemctl --user daemon-reload
systemctl --user enable --now ios-config-archive.timer

say "IOS config archive timer enabled (daily ~04:00 + jitter)"
say "Archive dir: $DATA_DIR/ios-config-archive"
say "Manual run:  $VENV_PY $REPO/ssh-ops-mcp/scripts/ios-config-drift-check.py"
say "One host:    .../ios-config-drift-check.py --host SWITCHNAME"
say "Logs:        journalctl --user -u ios-config-archive.service -n 50"
