#!/usr/bin/env bash
# Install daily IOS config archive + drift detection.
#
# Linux: systemd user timer (~04:00 + jitter)
# macOS: LaunchAgent (~04:00 daily)
#
#   bash admin-access/install-ios-config-archive.sh
set -Eeuo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=../install/lib/clawlab-platform.sh
source "$REPO/install/lib/clawlab-platform.sh"
clawlab_platform_init

DATA_DIR="${SSH_OPS_DATA:-${HOME}/.clawlab/ssh-ops/data}"
VENV_PY="${CLAW_PYTHON:-${HOME}/.clawlab/venv/bin/python3}"
DRIFT_SCRIPT="$REPO/ssh-ops-mcp/scripts/ios-config-drift-check.py"
LAUNCH_PLIST="$HOME/Library/LaunchAgents/com.clawlab.ios-config-archive.plist"

say() { printf '>> %s\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*" >&2; }

[[ -x "$VENV_PY" ]] || {
  echo "error: missing venv python at $VENV_PY (run install-clawstack.sh first)" >&2
  exit 1
}

[[ -f "$DRIFT_SCRIPT" ]] || {
  echo "error: missing $DRIFT_SCRIPT" >&2
  echo "hint: use the clawlab repo that contains commit 6fd5fb7+ (e.g. ~/AI/clawlab)" >&2
  exit 1
}

mkdir -p "$DATA_DIR/ios-config-archive" "$DATA_DIR/changes"
chmod 700 "$DATA_DIR/ios-config-archive" 2>/dev/null || true
chmod +x "$DRIFT_SCRIPT"

install_systemd_timer() {
  local unit_dir="${HOME}/.config/systemd/user"
  install -d -m 0755 "$unit_dir"
  install -m 0644 "$REPO/systemd-user/ios-config-archive.service" "$unit_dir/"
  install -m 0644 "$REPO/systemd-user/ios-config-archive.timer" "$unit_dir/"
  clawlab_sed_inplace "s|%h/clawlab|$REPO|g" "$unit_dir/ios-config-archive.service"
  clawlab_sed_inplace "s|%h/.clawlab/venv/bin/python3|$VENV_PY|g" "$unit_dir/ios-config-archive.service"
  systemctl --user daemon-reload
  systemctl --user enable --now ios-config-archive.timer
  say "systemd timer enabled (daily ~04:00 + jitter)"
  say "Logs: journalctl --user -u ios-config-archive.service -n 50"
}

install_launchd_timer() {
  mkdir -p "$HOME/Library/LaunchAgents"
  cat >"$LAUNCH_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.clawlab.ios-config-archive</string>
  <key>ProgramArguments</key>
  <array>
    <string>${VENV_PY}</string>
    <string>${DRIFT_SCRIPT}</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>4</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>${HOME}/.clawlab/run/ios-config-archive.log</string>
  <key>StandardErrorPath</key>
  <string>${HOME}/.clawlab/run/ios-config-archive.log</string>
</dict>
</plist>
PLIST
  mkdir -p "$HOME/.clawlab/run"
  launchctl bootout "gui/$(id -u)" "$LAUNCH_PLIST" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$LAUNCH_PLIST"
  say "LaunchAgent enabled (daily ~04:00): $LAUNCH_PLIST"
  say "Logs: $HOME/.clawlab/run/ios-config-archive.log"
}

if [[ "$CLAWLAB_SVC" == "systemd-user" ]]; then
  install_systemd_timer
elif [[ "$CLAWLAB_PLATFORM" == "macos" ]]; then
  install_launchd_timer
else
  warn "No scheduler available — archive dir ready; run manually:"
  say "  $VENV_PY $DRIFT_SCRIPT"
fi

say "Archive dir: $DATA_DIR/ios-config-archive"
say "Manual run:  $VENV_PY $DRIFT_SCRIPT"
say "One host:    $VENV_PY $DRIFT_SCRIPT --host SWITCHNAME"
