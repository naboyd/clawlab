#!/usr/bin/env bash
# install-mac.sh — greenfield Mac local-full install wrapper
#
# Usage:
#   bash install/install-mac.sh           # preinstall --fix + install --local-full + verify
#   bash install/install-mac.sh --yes     # non-interactive (install-clawstack --yes)
#   bash install/install-mac.sh --no-fix  # skip preinstall --fix
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
      sed -n '1,8p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
  shift
done

[[ "$(uname -s)" == Darwin ]] || { echo "ERROR: install-mac.sh is for macOS only" >&2; exit 1; }

log() { printf '==> %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

log "Mac greenfield install (local-full loopback stack)"
log "Repo: $REPO"

PRE_ARGS=(--mode=local-full)
[[ "$FIX" -eq 1 ]] && PRE_ARGS+=(--fix)

log "Step 1/3: preinstall-check ${PRE_ARGS[*]}"
bash "$SCRIPT_DIR/preinstall-check.sh" "${PRE_ARGS[@]}"

INST_ARGS=(--local-full)
[[ "$YES" -eq 1 ]] && INST_ARGS+=(--yes)

log "Step 2/3: install-clawstack ${INST_ARGS[*]}"
bash "$SCRIPT_DIR/install-clawstack.sh" "${INST_ARGS[@]}"

log "Step 3/3: verify-local-full"
bash "$SCRIPT_DIR/verify-local-full.sh"

log "Done. Portal: http://127.0.0.1:8083/  ·  Doctor: bash $SCRIPT_DIR/local-full-ctl.sh doctor"
log "Policy test: cd $REPO/tests && ./policy-test.sh --no-agent"
