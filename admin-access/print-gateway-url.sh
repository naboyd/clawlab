#!/usr/bin/env bash
# Print OpenClaw Control UI URLs with the full gateway token (safe parse).
set -euo pipefail

read_token() {
  python3 - <<'PY'
import os
from pathlib import Path

key = "OPENCLAW_GATEWAY_TOKEN"
home = Path(os.environ.get("OPENCLAW_HOME", Path.home() / ".openclaw")).expanduser()
val = os.environ.get(key, "").strip()
if not val:
    for fname in (".env", "gateway.systemd.env"):
        path = home / fname
        if not path.is_file():
            continue
        for line in path.read_text().splitlines():
            if line.startswith(f"{key}="):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
        if val:
            break
if not val:
    raise SystemExit(f"Missing {key} in {home}/.env or gateway.systemd.env")
print(val)
PY
}

TOKEN="$(read_token)"
LEN="${#TOKEN}"
DOMAIN="${DOMAIN:-lab.example.com}"
LAN_IP="${LAN_IP:-192.168.1.10}"
PORT="${PORT_PORTAL:-8443}"

portal_url() {
  local host="$1"
  local gw_enc
  gw_enc="$(python3 -c "from urllib.parse import quote; print(quote('wss://${host}:${PORT}/openclaw/', safe=''))")"
  echo "https://${host}:${PORT}/openclaw/?gatewayUrl=${gw_enc}#token=${TOKEN}"
}

echo "Token length: ${LEN} chars (expect 40+; if ~5, fix ~/.openclaw/.env duplicates)"
echo
echo "Loopback (SSH tunnel from Mac: ssh -N -L 18789:127.0.0.1:18789 user@lab-host):"
echo "  http://127.0.0.1:18789/openclaw/#token=${TOKEN}"
echo
echo "Portal HTTPS (gatewayUrl host must match the host in your browser address bar):"
echo "  FQDN:  $(portal_url "$DOMAIN")"
echo "  LAN:   $(portal_url "$LAN_IP")"
