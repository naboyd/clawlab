#!/usr/bin/env bash
# install-linux-lab.sh — greenfield Linux HTTPS lab host (unified portal :8443)
#
# Runs: preinstall (server checks) → install-clawstack (local agent stack)
#       → install-portals (nginx + claw-auth + MCP auth) → claw-auth doctor
#
# Use install-linux.sh instead for a loopback-only stack on :8083 (local-full).
#
# Usage:
#   bash install/install-linux-lab.sh
#   bash install/install-linux-lab.sh --yes
#   bash install/install-linux-lab.sh --no-fix
#
# Non-interactive portal (set before running):
#   DOMAIN=lab.example.com LE_EMAIL=admin@example.com LAN_IP=192.168.1.10 \
#     bash install/install-linux-lab.sh --yes
#
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"

YES=0
FIX=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y) YES=1 ;;
    --no-fix) FIX=0 ;;
    -h|--help)
      sed -n '1,18p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
  shift
done

[[ "$(uname -s)" == Linux ]] || { echo "ERROR: install-linux-lab.sh is for Linux only" >&2; exit 1; }

log() { printf '==> %s\n' "$*"; }

log "Linux lab host install (HTTPS portal :8443 + claw-auth)"
log "Repo: $REPO"

PRE_ARGS=(--mode=server)
[[ "$FIX" -eq 1 ]] && PRE_ARGS+=(--fix)

log "Step 1/4: preinstall-check ${PRE_ARGS[*]}"
bash "$SCRIPT_DIR/preinstall-check.sh" "${PRE_ARGS[@]}"

INST_ARGS=(--local)
[[ "$YES" -eq 1 ]] && INST_ARGS+=(--yes)

log "Step 2/4: install-clawstack ${INST_ARGS[*]} (agent stack — portal comes in step 3)"
bash "$SCRIPT_DIR/install-clawstack.sh" "${INST_ARGS[@]}"

PORTAL_ARGS=()
[[ "$YES" -eq 1 ]] && PORTAL_ARGS+=(--non-interactive --tls=https-le --auth=claw-auth)

log "Step 3/4: install-portals ${PORTAL_ARGS[*]:-(interactive)}"
bash "$REPO/claw-portals/install-portals.sh" "${PORTAL_ARGS[@]}"

log "Step 4/4: claw-auth doctor"
bash "$REPO/claw-auth/doctor.sh"

log "Done."
if [[ -f "$HOME/.claw-portals/config.env" ]]; then
  # shellcheck disable=SC1090
  source "$HOME/.claw-portals/config.env"
  scheme="https"
  [[ "${TLS_MODE:-https-le}" == "http" ]] && scheme="http"
  port="${PORT_PORTAL:-8443}"
  log "Portal: ${scheme}://${DOMAIN:-<host>}:${port}/"
fi
log "Create admin: ~/.clawlab/venv/bin/python $REPO/claw-auth/manage.py create-user admin"
log "Verify MCP:   bash $REPO/install/verify-local-full.sh  # only for :8083 local-full"
log "Redeploy:     bash $REPO/install/upgrade-clawstack.sh --restart --rebuild-mcp"
