#!/usr/bin/env bash
# install-webgui.sh — install DefenseClaw policy editor (loopback service)
#
# For full portal setup (TLS + centralized auth + nginx), prefer:
#   ../claw-portals/install-portals.sh
set -Eeuo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$SRC/.." && pwd)"
PORTALS="$REPO/claw-portals/install-portals.sh"

run_portals() {
  exec bash "$PORTALS" "$@"
}

if [[ "${1:-}" == "--portals" ]] || [[ ! -t 0 ]]; then
  run_portals "$@"
fi

echo "For TLS (HTTP/HTTPS) and centralized claw-auth, use:"
echo "  bash $PORTALS"
echo
read -r -p "Continue with loopback-only install? [y/N]: " ans
if [[ ! "$ans" =~ ^[Yy]$ ]]; then
  run_portals
fi

UNIT_DIR="$HOME/.config/systemd/user"
UNIT="defenseclaw-webgui.service"

echo "==> Python venv (PEP 668 safe)"
# shellcheck disable=SC1091
CLAWLAB_REPO="$REPO" source "$REPO/claw-portals/ensure-venv.sh"
ensure_clawlab_venv

echo "==> Dry-check config"
"$CLAW_PYTHON" -c "
import sys
sys.path.insert(0, '$SRC')
import policy_store as ps
cfg = ps.load_config()
print('OK: loaded', ps.CONFIG_PATH)
" || {
  echo "WARN: ~/.defenseclaw/config.yaml not found yet."
}

echo "==> Installing systemd user unit -> $UNIT_DIR/$UNIT"
install -d -m 0755 "$UNIT_DIR"
sed "s|%h/clawlab/defenseclaw-webgui|$SRC|g" "$SRC/$UNIT" > "$UNIT_DIR/$UNIT"

loginctl enable-linger "$USER" 2>/dev/null || true
systemctl --user daemon-reload
systemctl --user enable --now "$UNIT"

echo "Done. http://127.0.0.1:8770 (loopback only)"
echo "Python: $CLAW_PYTHON"
echo "For LAN access: bash $PORTALS"
