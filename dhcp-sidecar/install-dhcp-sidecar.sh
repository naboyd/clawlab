#!/usr/bin/env bash
# Install dhcp-sidecar on an ISC DHCP server (Phase A).
# Run as root on the target host (e.g. Services).
set -Eeuo pipefail

REPO="${CLAWLAB_REPO:-$(cd "$(dirname "$0")/.." && pwd)}"
SRC="$REPO/dhcp-sidecar"
DEST="${DHCP_SIDECAR_DEST:-/opt/clawlab/dhcp-sidecar}"
ENV_FILE="${DHCP_SIDECAR_ENV:-/etc/dhcp-sidecar/env}"
UNIT_DEST="/etc/systemd/system/dhcp-sidecar.service"
PY="${DHCP_SIDECAR_PYTHON:-python3}"

say() { printf '>> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || die "run as root"

[[ -d "$SRC" ]] || die "missing $SRC (set CLAWLAB_REPO)"

say "Installing dhcp-sidecar to $DEST"
install -d -m 0755 "$DEST"
install -m 0644 "$SRC/app.py" "$SRC/dhcp_ops.py" "$SRC/requirements.txt" "$DEST/"
install -d -m 0755 "$DEST/venv"
if [[ ! -x "$DEST/venv/bin/python" ]]; then
  "$PY" -m venv "$DEST/venv"
fi
"$DEST/venv/bin/pip" install -q -r "$DEST/requirements.txt"

install -d -m 0750 /etc/dhcp-sidecar
install -d -m 0755 /etc/dhcp/dhcpd.d
install -d -m 0750 /var/lib/dhcp-sidecar

if [[ ! -f "$ENV_FILE" ]]; then
  token="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  secret="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  umask 077
  cat >"$ENV_FILE" <<EOF
# dhcp-sidecar — chmod 640, root-only. Bearer token for API + Web UI login.
DHCP_SIDECAR_TOKEN=${token}
DHCP_SIDECAR_SECRET=${secret}
DHCP_SIDECAR_HOST=127.0.0.1
DHCP_SIDECAR_PORT=9080
EOF
  chmod 640 "$ENV_FILE"
  chown root:root "$ENV_FILE"
  say "Created $ENV_FILE (save the token — shown once below)"
  echo ""
  grep DHCP_SIDECAR_TOKEN= "$ENV_FILE"
  echo ""
else
  say "Keeping existing $ENV_FILE"
fi

install -m 0644 "$SRC/systemd/dhcp-sidecar.service" "$UNIT_DEST"
systemctl daemon-reload
systemctl enable --now dhcp-sidecar.service
systemctl --no-pager --full status dhcp-sidecar.service | head -15

say "Local UI:  http://127.0.0.1:9080/  (SSH tunnel from your Mac if remote)"
say "Health:    curl -s http://127.0.0.1:9080/health"
say "API docs:  see $SRC/README.md"
