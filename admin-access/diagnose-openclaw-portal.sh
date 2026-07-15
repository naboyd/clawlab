#!/usr/bin/env bash
# Diagnose OpenClaw Control UI behind claw-auth + nginx (/openclaw/).
set -euo pipefail

OC_JSON="${OPENCLAW_CONFIG:-$HOME/.openclaw/openclaw.json}"
PORT="${PORT_PORTAL:-8443}"
DOMAIN="${DOMAIN:-icecream.naboydciscolab.com}"
LAN_IP="${LAN_IP:-192.168.128.93}"

echo "=== OpenClaw portal diagnostics ==="
echo

if [[ ! -f "$OC_JSON" ]]; then
  echo "MISSING: $OC_JSON"
  exit 1
fi

python3 - "$OC_JSON" <<'PY'
import json, sys
p = sys.argv[1]
c = json.load(open(p))
gw = c.get("gateway", {})
auth = gw.get("auth", {})
ui = gw.get("controlUi", {})
print("gateway.bind:", gw.get("bind"))
print("gateway.port:", gw.get("port", 18789))
print("auth.mode:", auth.get("mode"))
print("auth.token:", "SET" if auth.get("token") else "none")
print("auth.password:", auth.get("password", "none"))
tp = auth.get("trustedProxy") or {}
print("trustedProxy.allowLoopback:", tp.get("allowLoopback"))
print("trustedProxies:", gw.get("trustedProxies"))
print("controlUi.basePath:", ui.get("basePath"))
print("controlUi.allowedOrigins:")
for o in ui.get("allowedOrigins") or []:
    print("  -", o)
PY

echo
echo "--- systemd ---"
systemctl --user is-active openclaw-gateway.service 2>/dev/null || echo "openclaw-gateway: not active"
systemctl --user is-active claw-auth.service 2>/dev/null || echo "claw-auth: not active"

echo
echo "--- loopback HTTP ---"
code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:18789/openclaw/" 2>/dev/null || echo 000)"
echo "GET http://127.0.0.1:18789/openclaw/ -> HTTP $code (expect 200)"

echo
echo "--- portal HTTPS (no cookie) ---"
code="$(curl -sk -o /dev/null -w '%{http_code}' "https://${LAN_IP}:${PORT}/openclaw/" 2>/dev/null || echo 000)"
echo "GET https://${LAN_IP}:${PORT}/openclaw/ -> HTTP $code (expect 302 to login without cookie)"

echo
echo "--- devices (pairing) ---"
if command -v openclaw >/dev/null 2>&1; then
  openclaw devices list 2>/dev/null || echo "(openclaw devices list failed)"
else
  echo "(openclaw CLI not in PATH)"
fi

echo
echo "--- recent gateway WS/auth log lines ---"
echo "(gateway-client + Go-http-client = internal backend; browser shows Mozilla/Chrome/Safari)"
journalctl --user -u openclaw-gateway --since "10 min ago" --no-pager 2>/dev/null \
  | grep -iE 'unauthorized|trusted_proxy|origin|pair|1008|ws |startup|failed' \
  | tail -20 || true

echo
echo "Browser origin must exactly match an allowedOrigins entry, e.g.:"
echo "  https://${DOMAIN}:${PORT}"
echo "  https://${LAN_IP}:${PORT}"
echo
echo "While the browser shows the connection error, re-run:"
echo "  openclaw devices list"
echo "  journalctl --user -u openclaw-gateway -f"
echo "Look for: trusted_proxy_user_missing | origin | pairing | 1008"
