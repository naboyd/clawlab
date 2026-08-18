#!/usr/bin/env bash
# clawlab-install-log.sh — append installer output to ~/.clawlab/run/install.log
# Source from install scripts; do not run directly.
set -Eeuo pipefail

CLAWLAB_RUN="${CLAWLAB_RUN:-$HOME/.clawlab/run}"
CLAWLAB_INSTALL_LOG="${CLAWLAB_INSTALL_LOG:-$CLAWLAB_RUN/install.log}"

clawlab_install_log_ts() {
  if date -Iseconds >/dev/null 2>&1; then
    date -Iseconds
  elif date -u +%Y-%m-%dT%H:%M:%SZ >/dev/null 2>&1; then
    date -u +%Y-%m-%dT%H:%M:%SZ
  else
    date
  fi
}

# Begin tee'd logging once per install chain (nested installers skip if already active).
clawlab_install_log_begin() {
  local name="$1"
  shift || true
  [[ "${CLAWLAB_INSTALL_LOGGING:-0}" == 1 ]] && return 0
  export CLAWLAB_INSTALL_LOGGING=1
  mkdir -p "$CLAWLAB_RUN"
  {
    echo
    echo "================================================================"
    echo " clawlab install: $name"
    echo " started: $(clawlab_install_log_ts)"
    echo " user: $(whoami)  host: $(hostname -s 2>/dev/null || hostname)"
    echo " pwd: $(pwd)"
    echo " args: $*"
    echo " log:  $CLAWLAB_INSTALL_LOG"
    echo "================================================================"
  } >>"$CLAWLAB_INSTALL_LOG"
  exec > >(tee -a "$CLAWLAB_INSTALL_LOG") 2>&1
}

clawlab_install_log_end() {
  local name="$1"
  local rc="${2:-0}"
  [[ "${CLAWLAB_INSTALL_LOGGING:-0}" != 1 ]] && return 0
  {
    echo "================================================================"
    echo " clawlab install: $name finished exit=$rc at $(clawlab_install_log_ts)"
    echo "================================================================"
    echo
  } >>"$CLAWLAB_INSTALL_LOG"
}
