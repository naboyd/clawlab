#!/usr/bin/env bash
# Quick checks for OpenClaw WebSocket path through nginx.
set -euo pipefail

LAN_IP="${LAN_IP:-192.168.1.10}"
PORT="${PORT_PORTAL:-8443}"
BASE="https://${LAN_IP}:${PORT}/openclaw/"

echo "=== OpenClaw WSS path tests ==="
echo

echo "--- HTTP shell (expect 200) ---"
curl -sk -o /dev/null -w "GET ${BASE} -> %{http_code}\n" "$BASE"

echo
echo "--- WebSocket upgrade via nginx (expect 101) ---"
headers="$(curl -sk --max-time 3 -D - -o /dev/null \
  -H "Connection: Upgrade" \
  -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Version: 13" \
  -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
  "$BASE" 2>/dev/null | head -1)" || true
echo "$headers"
case "$headers" in
  *"101"*) echo "OK: nginx forwarded WebSocket upgrade" ;;
  *) echo "FAIL: expected HTTP/1.1 101 — nginx or gateway rejected upgrade" ;;
esac

echo
echo "--- loopback upgrade (expect 101) ---"
headers="$(curl -s --max-time 3 -D - -o /dev/null \
  -H "Connection: Upgrade" \
  -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Version: 13" \
  -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
  "http://127.0.0.1:18789/openclaw/" 2>/dev/null | head -1)" || true
echo "$headers"
case "$headers" in
  *"101"*) echo "OK: loopback forwarded WebSocket upgrade" ;;
  *) echo "FAIL: expected HTTP/1.1 101 on loopback" ;;
esac

echo
echo "While browser shows WSS error, run:"
echo "  journalctl --user -u openclaw-gateway -f"
echo "  openclaw devices list"
echo "  openclaw devices approve --latest   # if pending"
echo
echo "Clear stale Control UI cache: DevTools → Application → Service Workers → Unregister"
