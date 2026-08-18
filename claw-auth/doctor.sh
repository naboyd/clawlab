#!/usr/bin/env bash
# doctor.sh — claw-auth health + optional lab portal verification
#
# Appends each run to ~/.clawlab/run/claw-auth-doctor.log (override: CLAWLAB_DOCTOR_LOG).
#
# Usage:
#   bash claw-auth/doctor.sh
#   bash claw-auth/doctor.sh --verify-lab-portal
#   bash claw-auth/doctor.sh --no-log
#
set -Eeuo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${CLAWLAB_VENV:-$HOME/.clawlab/venv}"
PY="${CLAW_PYTHON:-$VENV/bin/python}"
AUTH_HOME="${CLAW_AUTH_HOME:-$HOME/.claw-auth}"
AUTH_LOG="${CLAW_AUTH_LOG:-$AUTH_HOME/auth.log}"
CLAWLAB_RUN="${CLAWLAB_RUN:-$HOME/.clawlab/run}"
DOCTOR_LOG="${CLAWLAB_DOCTOR_LOG:-$CLAWLAB_RUN/claw-auth-doctor.log}"
PORTALS_CONFIG="${CLAW_PORTALS_CONFIG:-$HOME/.claw-portals/config.env}"

VERIFY_LAB=0
NO_LOG=0
FAIL=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --verify-lab-portal|--lab-portal) VERIFY_LAB=1 ;;
    --no-log) NO_LOG=1 ;;
    -h|--help)
      sed -n '1,14p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown option: $1 (try --help)" >&2; exit 1 ;;
  esac
  shift
done

doctor_ts() {
  if date -Iseconds >/dev/null 2>&1; then
    date -Iseconds
  elif date -u +%Y-%m-%dT%H:%M:%SZ >/dev/null 2>&1; then
    date -u +%Y-%m-%dT%H:%M:%SZ
  else
    date
  fi
}

should_verify_lab_portal() {
  [[ "$VERIFY_LAB" -eq 1 ]] && return 0
  [[ ! -f "$PORTALS_CONFIG" ]] && return 1
  # shellcheck disable=SC1090
  source "$PORTALS_CONFIG"
  [[ "${PORT_PORTAL:-8443}" != "8083" ]] && return 0
  [[ "${TLS_MODE:-}" != "http" && -n "${TLS_MODE:-}" ]] && return 0
  [[ "${SCHEME:-}" == "https" ]] && return 0
  return 1
}

run_claw_auth_doctor() {
  echo "=== claw-auth doctor ==="
  echo "time: $(doctor_ts)"
  echo "log:  $DOCTOR_LOG"
  echo

  echo "--- systemd ---"
  if systemctl --user is-active claw-auth.service >/dev/null 2>&1; then
    echo "claw-auth.service: active"
  else
    echo "claw-auth.service: not active"
    FAIL=1
  fi
  systemctl --user is-enabled claw-auth.service 2>/dev/null || true
  echo

  echo "--- journal (last 15 lines) ---"
  journalctl --user -u claw-auth -n 15 --no-pager 2>/dev/null || echo "(no journal entries)"
  echo

  echo "--- loopback health ---"
  if curl -fsS "http://127.0.0.1:8780/healthz" >/dev/null 2>&1; then
    echo "OK: http://127.0.0.1:8780/healthz"
  else
    echo "FAIL: http://127.0.0.1:8780/healthz"
    FAIL=1
  fi
  verify_code="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8780/verify 2>/dev/null || echo 000)"
  echo "GET /verify -> HTTP $verify_code (expect 401 without cookie)"
  [[ "$verify_code" == "401" ]] || FAIL=1
  echo

  echo "--- auth files ---"
  ls -la "$AUTH_HOME" 2>/dev/null || echo "missing $AUTH_HOME"
  if [[ -f "$AUTH_LOG" ]]; then
    echo "tail $AUTH_LOG:"
    tail -n 10 "$AUTH_LOG"
  else
    echo "no file log yet at $AUTH_LOG"
  fi
  echo

  echo "--- users ---"
  if [[ -x "$PY" ]]; then
    "$PY" "$REPO/claw-auth/manage.py" list-users 2>/dev/null || echo "(manage.py failed)"
  else
    echo "venv python missing at $PY"
    FAIL=1
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
  if [[ -f "$PORTALS_CONFIG" ]]; then
    grep -E '^(TLS_MODE|AUTH_MODE|SCHEME|DOMAIN|LAN_IP|PORT_)' "$PORTALS_CONFIG" || true
  else
    echo "missing $PORTALS_CONFIG (local-full :8083 may not use install-portals)"
  fi
  echo
}

run_lab_portal_verify() {
  echo "--- lab portal verification ---"
  local verify_script="$REPO/install/verify-lab-portal.sh"
  if [[ ! -f "$verify_script" ]]; then
    echo "FAIL: missing $verify_script"
    FAIL=1
    return
  fi
  if bash "$verify_script"; then
    echo "OK: lab portal checks passed"
  else
    echo "FAIL: lab portal checks failed (see above)"
    FAIL=1
  fi
  echo
}

run_doctor() {
  run_claw_auth_doctor
  if should_verify_lab_portal; then
    run_lab_portal_verify
  elif [[ "$VERIFY_LAB" -eq 1 ]]; then
    echo "--- lab portal verification ---"
    echo "WARN: $PORTALS_CONFIG missing — run install-portals.sh first"
    FAIL=1
    echo
  fi

  if [[ "$FAIL" -eq 0 ]]; then
    echo "Done. Log: $DOCTOR_LOG · install log: $CLAWLAB_RUN/install.log"
    echo "After a login attempt, re-run and check journal + $AUTH_LOG"
  else
    echo "Done with failures. Log: $DOCTOR_LOG · install log: $CLAWLAB_RUN/install.log"
    echo "Fix FAIL items above; ssh-ops: bash $REPO/ssh-ops-mcp/doctor.sh"
  fi
}

mkdir -p "$CLAWLAB_RUN"

if [[ "$NO_LOG" -eq 1 ]]; then
  run_doctor
else
  {
    echo
    echo "======== claw-auth doctor $(doctor_ts) ========"
    run_doctor
  } | tee -a "$DOCTOR_LOG"
fi

exit "$FAIL"
