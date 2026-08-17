#!/usr/bin/env bash
# ensure-venv.sh — shared Python venv for clawlab portal services (PEP 668 safe)
#
# Usage:
#   source "$(dirname "$0")/ensure-venv.sh"
#   ensure_clawlab_venv
#   "$CLAW_PYTHON" ...
#
set -Eeuo pipefail

VENV_DIR="${CLAWLAB_VENV:-$HOME/.clawlab/venv}"
REPO="${CLAWLAB_REPO:-$(cd "$(dirname "${BASH_SOURCE[1]:-${BASH_SOURCE[0]}}")/.." && pwd)}"

ensure_clawlab_venv() {
  if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    echo "==> Creating Python venv at $VENV_DIR"
    if ! python3 -m venv "$VENV_DIR" 2>/dev/null; then
      echo "==> python3-venv not available; installing python3-venv python3-full"
      if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update -o Acquire::Retries=3
        sudo apt-get install -y python3-venv python3-full
      else
        echo "ERROR: install python3-venv, then re-run." >&2
        return 1
      fi
      python3 -m venv "$VENV_DIR"
    fi
  fi

  echo "==> Installing portal Python deps into venv"
  "$VENV_DIR/bin/pip" install -q --upgrade pip
  for req in \
    "$REPO/claw-auth/requirements.txt" \
    "$REPO/defenseclaw-webgui/requirements.txt" \
    "$REPO/ssh-ops-mcp/requirements.txt"; do
    if [[ -f "$req" ]]; then
      "$VENV_DIR/bin/pip" install -q -r "$req"
    fi
  done

  export CLAWLAB_VENV="$VENV_DIR"
  export CLAW_PYTHON="$VENV_DIR/bin/python"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  ensure_clawlab_venv
  echo "CLAWLAB_VENV=$CLAWLAB_VENV"
  echo "CLAW_PYTHON=$CLAW_PYTHON"
fi
