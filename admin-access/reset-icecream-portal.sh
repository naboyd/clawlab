#!/usr/bin/env bash
# Phase 1 baseline: unified HTTPS portal on :8443, claw-auth, token-mode OpenClaw.
# Run on icecream from ~/clawlab after git pull.
#
# Usage:
#   bash admin-access/reset-icecream-portal.sh
#   SKIP_GIT_PULL=1 SKIP_PODMAN=1 bash admin-access/reset-icecream-portal.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DOMAIN="${DOMAIN:-icecream.naboydciscolab.com}"
LAN_IP="${LAN_IP:-192.168.128.93}"
PORT="${PORT_PORTAL:-8443}"
VENV="${CLAWLAB_VENV:-$HOME/.clawlab/venv}"
PY="${CLAW_PYTHON:-$VENV/bin/python}"
export PATH="$HOME/.npm-global/bin:$HOME/bin:$HOME/.local/bin:/usr/local/bin:$PATH"
export DOMAIN LAN_IP PORT_PORTAL="$PORT"

pass() { echo "  OK: $*"; }
fail() { echo "  FAIL: $*" >&2; FAILED=1; }
warn() { echo "  WARN: $*"; }

FAILED=0

echo "=============================================="
echo " clawlab Phase 1 — portal baseline reset"
echo " repo: $REPO"
echo " host: $(hostname -f 2>/dev/null || hostname)"
echo " time: $(date -Is)"
echo "=============================================="
echo

if [[ "${SKIP_GIT_PULL:-0}" != "1" ]] && git -C "$REPO" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "==> git pull (optional; set SKIP_GIT_PULL=1 to skip)"
  git -C "$REPO" pull --ff-only || warn "git pull failed — continuing with local tree"
  echo
fi

echo "==> unified portal installer (nginx + claw-auth + LE)"
bash "$REPO/claw-portals/install-portals.sh" --non-interactive --tls=https-le --auth=claw-auth
echo

echo "==> OpenClaw token-mode portal config"
python3 "$REPO/admin-access/apply-token-portal.py"
echo

echo "==> restart user services"
systemctl --user restart openclaw-gateway claw-auth defenseclaw-webgui
sleep 2
systemctl --user is-active openclaw-gateway.service && pass "openclaw-gateway active" || fail "openclaw-gateway not active"
systemctl --user is-active claw-auth.service && pass "claw-auth active" || fail "claw-auth not active"
systemctl --user is-active defenseclaw-webgui.service && pass "defenseclaw-webgui active" || fail "defenseclaw-webgui not active"
echo

if [[ "${SKIP_PODMAN:-0}" != "1" ]] && command -v podman >/dev/null 2>&1; then
  echo "==> rebuild ssh-ops image (set SKIP_PODMAN=1 to skip)"
  podman build -t ssh-ops:latest "$REPO/ssh-ops-mcp"
  systemctl --user restart ssh-ops-gui 2>/dev/null || warn "ssh-ops-gui unit not found or restart failed"
  sleep 5
  echo
else
  warn "skipping podman rebuild"
  systemctl --user try-restart ssh-ops-gui 2>/dev/null || true
  sleep 3
  echo
fi

echo "==> disable legacy per-port nginx sites (conflict with unified :${PORT} portal)"
legacy_removed=0
for legacy in openclaw-control.conf ssh-ops-admin.conf openclaw-admin.conf defenseclaw-admin.conf; do
  if [[ -e "/etc/nginx/sites-enabled/$legacy" ]]; then
    sudo rm -f "/etc/nginx/sites-enabled/$legacy"
    legacy_removed=1
    pass "removed sites-enabled/$legacy"
  fi
done
if [[ "$legacy_removed" == "1" ]]; then
  if sudo nginx -t >/dev/null 2>&1; then
    sudo systemctl reload nginx
    pass "nginx reloaded after legacy site cleanup"
  else
    fail "nginx -t failed after legacy site cleanup"
    sudo nginx -t 2>&1 | sed 's/^/    /' >&2 || true
  fi
else
  pass "no legacy nginx sites to remove (install-portals already unified)"
fi
echo

echo "==> nginx sites (expect only clawlab-portal.conf)"
legacy_left=0
for legacy in openclaw-control.conf ssh-ops-admin.conf openclaw-admin.conf defenseclaw-admin.conf; do
  if [[ -e "/etc/nginx/sites-enabled/$legacy" ]]; then
    fail "legacy site still enabled: $legacy (re-run installer or sudo rm sites-enabled/$legacy)"
    legacy_left=1
  fi
done
if ls /etc/nginx/sites-enabled/clawlab-*.conf >/dev/null 2>&1; then
  ls -1 /etc/nginx/sites-enabled/clawlab-*.conf
  count="$(ls -1 /etc/nginx/sites-enabled/clawlab-*.conf 2>/dev/null | wc -l | tr -d ' ')"
  if [[ "$count" == "1" ]] && [[ -L /etc/nginx/sites-enabled/clawlab-portal.conf || -f /etc/nginx/sites-enabled/clawlab-portal.conf ]]; then
    pass "single unified nginx site"
  else
    warn "multiple clawlab nginx sites — legacy per-port configs may still be enabled"
  fi
else
  fail "no clawlab nginx sites in sites-enabled"
fi
echo

echo "==> loopback backends"
code="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18789/openclaw/ 2>/dev/null || echo 000)"
[[ "$code" == "200" || "$code" == "302" ]] && pass "OpenClaw /openclaw/ -> HTTP $code" || fail "OpenClaw /openclaw/ -> HTTP $code"

code="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8770/ 2>/dev/null || echo 000)"
[[ "$code" == "200" || "$code" == "302" || "$code" == "401" || "$code" == "403" ]] && pass "DefenseClaw :8770 -> HTTP $code" || fail "DefenseClaw :8770 -> HTTP $code"

loop_code="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8765/ 2>/dev/null || echo 000)"
if [[ "$loop_code" == "200" || "$loop_code" == "302" || "$loop_code" == "401" || "$loop_code" == "403" ]]; then
  pass "ssh-ops GUI :8765 -> HTTP $loop_code"
else
  portal_code="$(curl -sk -o /dev/null -w '%{http_code}' "https://${LAN_IP}:${PORT}/ssh-ops/" 2>/dev/null || echo 000)"
  if [[ "$portal_code" == "200" || "$portal_code" == "302" || "$portal_code" == "401" || "$portal_code" == "403" ]]; then
    pass "ssh-ops via portal /ssh-ops/ -> HTTP $portal_code (loopback :8765 was $loop_code)"
  else
    fail "ssh-ops unreachable (loopback :8765=$loop_code, portal /ssh-ops/=$portal_code)"
  fi
fi

curl -fsS http://127.0.0.1:8780/healthz >/dev/null 2>&1 && pass "claw-auth healthz" || fail "claw-auth healthz"
echo

echo "==> portal HTTPS (no cookie — expect redirect to login)"
for host in "$LAN_IP" "$DOMAIN"; do
  code="$(curl -sk -o /dev/null -w '%{http_code}' "https://${host}:${PORT}/" 2>/dev/null || echo 000)"
  [[ "$code" == "200" || "$code" == "302" ]] && pass "https://${host}:${PORT}/ -> HTTP $code" || fail "https://${host}:${PORT}/ -> HTTP $code"
done
echo

echo "==> OpenClaw /openclaw/ via portal (no auth on path — expect 200)"
code="$(curl -sk -o /dev/null -w '%{http_code}' "https://${LAN_IP}:${PORT}/openclaw/" 2>/dev/null || echo 000)"
[[ "$code" == "200" || "$code" == "302" ]] && pass "portal /openclaw/ -> HTTP $code" || fail "portal /openclaw/ -> HTTP $code"
echo

if [[ -x "$REPO/admin-access/test-openclaw-wss.sh" ]]; then
  echo "==> WebSocket upgrade via nginx"
  wss_line="$(curl -sk --max-time 3 -D - -o /dev/null \
    -H "Connection: Upgrade" -H "Upgrade: websocket" \
    -H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
    "https://${LAN_IP}:${PORT}/openclaw/" 2>/dev/null | head -1 || true)"
  echo "  $wss_line"
  if [[ "$wss_line" == *"101"* ]]; then
    pass "nginx WSS upgrade -> 101"
  else
    fail "nginx WSS upgrade did not return 101"
  fi
  echo
fi

if command -v openclaw >/dev/null 2>&1; then
  echo "==> OpenClaw gateway status"
  if openclaw gateway status 2>&1 | grep -q "Connectivity probe: ok"; then
    pass "gateway connectivity probe ok"
  else
    fail "gateway connectivity probe not ok"
    openclaw gateway status 2>&1 | grep -E "Connectivity|Capability|failed|pairing" || true
  fi
  echo
fi

echo "==> claw-auth doctor"
bash "$REPO/claw-auth/doctor.sh" || warn "claw-auth doctor reported issues"
echo

echo "==> hub OpenClaw link shape (authd must use X-Forwarded-Host for gatewayUrl)"
if [[ -x "$PY" ]]; then
  if ! "$PY" - "$REPO" <<'PY'
import sys
from pathlib import Path

repo = Path(sys.argv[1])
text = (repo / "claw-auth" / "authd.py").read_text()
if "host_header" in text and "X-Forwarded-Host" in text:
    print("  OK: authd uses X-Forwarded-Host for gatewayUrl")
else:
    print("  FAIL: authd missing host-aware gatewayUrl — git pull and restart claw-auth")
    sys.exit(1)
PY
  then
    fail "authd missing X-Forwarded-Host gatewayUrl fix"
  fi
else
  warn "venv python not found — skipping authd self-check"
fi
echo

echo "=============================================="
if [[ "$FAILED" -eq 0 ]]; then
  echo " Phase 1 PASSED — portal shell is healthy."
  echo
  echo " Bookmark: https://${DOMAIN}:${PORT}/"
  echo " Next (Phase 2): incognito -> login -> Open OpenClaw (new window)."
  echo " Do NOT test OpenClaw via plain /openclaw/ bookmark without #token=."
  if [[ -x "$REPO/admin-access/print-gateway-url.sh" ]]; then
    echo
    bash "$REPO/admin-access/print-gateway-url.sh" 2>/dev/null || true
  fi
else
  echo " Phase 1 FAILED — fix items marked FAIL above before Phase 2."
  exit 1
fi
echo "=============================================="
