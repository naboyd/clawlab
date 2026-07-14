#!/usr/bin/env bash
# doctor.sh — quick claw-auth health / login diagnostics
set -Eeuo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${CLAWLAB_VENV:-$HOME/.clawlab/venv}"
PY="${CLAW_PYTHON:-$VENV/bin/python}"
AUTH_HOME="${CLAW_AUTH_HOME:-$HOME/.claw-auth}"
LOG="$AUTH_HOME/auth.log"

echo "=== claw-auth doctor ==="
echo "time: $(date -Is)"
echo

echo "--- systemd ---"
systemctl --user is-active claw-auth.service 2>/dev/null || echo "claw-auth.service: not active"
systemctl --user is-enabled claw-auth.service 2>/dev/null || true
echo

echo "--- journal (last 15 lines) ---"
journalctl --user -u claw-auth -n 15 --no-pager 2>/dev/null || echo "(no journal entries)"
echo

echo "--- loopback health ---"
curl -fsS "http://127.0.0.1:8780/healthz" 2>/dev/null && echo || echo "FAIL: http://127.0.0.1:8780/healthz"
code="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8780/verify)"
echo "GET /verify -> HTTP $code (expect 401 without cookie)"
echo

echo "--- auth files ---"
ls -la "$AUTH_HOME" 2>/dev/null || echo "missing $AUTH_HOME"
if [[ -f "$LOG" ]]; then
  echo "tail $LOG:"
  tail -n 10 "$LOG"
else
  echo "no file log yet at $LOG"
fi
echo

echo "--- users ---"
if [[ -x "$PY" ]]; then
  "$PY" "$REPO/claw-auth/manage.py" list-users 2>/dev/null || echo "(manage.py failed)"
else
  echo "venv python missing at $PY"
fi
echo

echo "--- nginx clawlab sites ---"
if command -v nginx >/dev/null 2>&1; then
  ls -la /etc/nginx/sites-enabled/clawlab-*.conf 2>/dev/null || echo "no clawlab nginx sites"
else
  echo "nginx not installed"
fi
echo

echo "--- portal config ---"
if [[ -f "$HOME/.claw-portals/config.env" ]]; then
  grep -E '^(AUTH_MODE|CLAW_AUTH_PREFIX|PORT_)' "$HOME/.claw-portals/config.env" || true
else
  echo "missing ~/.claw-portals/config.env"
fi
echo

echo "Done. After a login attempt, re-run and check journal + $LOG"
