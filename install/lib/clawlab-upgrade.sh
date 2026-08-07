#!/usr/bin/env bash
# clawlab-upgrade.sh — shared helpers for upgrade-clawstack.sh
# Source only; do not execute directly.
set -Eeuo pipefail

# upgrade_git_check DIR [REMOTE_REF]
# Prints: unchanged|updated|cloned|missing|dirty
# On updated/cloned, leaves repo at REMOTE_REF (default origin/HEAD).
upgrade_git_check() {
  local dir="$1" remote_ref="${2:-origin/HEAD}"
  [[ -d "$dir" ]] || { echo missing; return 0; }
  [[ -d "$dir/.git" ]] || { echo missing; return 0; }

  local before upstream
  before="$(git -C "$dir" rev-parse HEAD 2>/dev/null)" || { echo missing; return 0; }

  if [[ -n "$(git -C "$dir" status --porcelain 2>/dev/null)" ]]; then
    echo dirty
    return 0
  fi

  git -C "$dir" fetch --quiet origin 2>/dev/null || { echo fetch-failed; return 0; }

  local branch="${UPGRADE_GIT_BRANCH:-}"
  if [[ -z "$branch" ]]; then
    branch="$(git -C "$dir" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  fi
  if [[ -n "$branch" && "$branch" != HEAD ]]; then
    if git -C "$dir" rev-parse "origin/${branch}" >/dev/null 2>&1; then
      remote_ref="origin/${branch}"
    fi
  fi

  if ! git -C "$dir" rev-parse "$remote_ref" >/dev/null 2>&1; then
    remote_ref="origin/HEAD"
  fi
  upstream="$(git -C "$dir" rev-parse "$remote_ref" 2>/dev/null)" || { echo fetch-failed; return 0; }

  if [[ "$before" == "$upstream" ]]; then
    echo unchanged
    return 0
  fi

  git -C "$dir" reset --hard "$upstream" >/dev/null
  echo updated
}

upgrade_git_short() {
  local dir="$1"
  git -C "$dir" rev-parse --short HEAD 2>/dev/null || echo "?"
}

upgrade_openclaw_build() {
  local src="$1" bin="$2"
  clawlab_prepend_openclaw_node_path || true
  clawlab_install_node "$CLAWLAB_OPENCLAW_NODE_MAJOR" || return 1
  clawlab_install_pnpm || return 1
  ( cd "$src" && pnpm install --frozen-lockfile && pnpm build ) || return 1
  mkdir -p "$bin"
  ln -sf "$src/dist/index.js" "$bin/openclaw"
  chmod +x "$bin/openclaw" 2>/dev/null || true
  [[ -f "$src/dist/index.js" ]] || return 1
  return 0
}

upgrade_defenseclaw_build() {
  local src="$1" bin="$2"
  clawlab_install_uv || return 1
  rm -f "$bin/.defenseclaw-source-root" 2>/dev/null || true
  ( cd "$src" && ./scripts/install.sh --yes --connector openclaw ) || return 1
  return 0
}

#!/usr/bin/env bash
# clawlab-upgrade.sh — shared helpers for upgrade-clawstack.sh
# Source only; do not execute directly.
set -Eeuo pipefail

upgrade_port_open() {
  local port="$1"
  python3 - "$port" <<'PY'
import socket, sys
s = socket.socket()
s.settimeout(0.4)
try:
    s.connect(("127.0.0.1", int(sys.argv[1])))
except OSError:
    raise SystemExit(1)
finally:
    s.close()
PY
}

clawlab_detect_local_full() {
  [[ -f "$HOME/.claw-portals/config.env" ]] && return 0
  [[ -x "${1:-}/install/local-full-ctl.sh" ]] && upgrade_port_open "${LOCAL_FULL_PORT:-8083}" && return 0
  return 1
}
