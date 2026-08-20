# shellcheck shell=bash
# Ensure OpenClaw plugin extensions are complete before gateway restarts.
#
# Source from admin scripts:
#   source "$REPO/admin-access/lib/ensure-openclaw-extensions.sh"
#   ensure_defenseclaw_openclaw_extension || exit 1

ensure_defenseclaw_openclaw_extension() {
  local dest="${OPENCLAW_EXTENSIONS_DIR:-$HOME/.openclaw/extensions}/defenseclaw"
  local index="$dest/dist/index.js"

  if [[ -f "$index" ]]; then
    return 0
  fi

  local -a sources=(
    "${DEFENSECLAW_HOME:-$HOME/.defenseclaw}/extensions/defenseclaw"
    "${DEFENSECLAW_SRC:-$HOME/src/defenseclaw}/extensions/defenseclaw"
  )

  local src
  for src in "${sources[@]}"; do
    [[ -f "$src/dist/index.js" ]] || continue
    mkdir -p "$(dirname "$dest")"
    rm -rf "$dest"
    cp -a "$src" "$dest"
    printf '>> Restored defenseclaw OpenClaw extension from %s\n' "$src" >&2
    return 0
  done

  local build_src="${DEFENSECLAW_SRC:-$HOME/src/defenseclaw}/extensions/defenseclaw"
  if [[ -f "$build_src/package.json" ]] && command -v npm >/dev/null 2>&1; then
    if ( cd "$build_src" && npm run build --silent >/dev/null 2>&1 ); then
      mkdir -p "$(dirname "$dest")"
      rm -rf "$dest"
      cp -a "$build_src" "$dest"
      printf '>> Built and installed defenseclaw OpenClaw extension from %s\n' "$build_src" >&2
      return 0
    fi
  fi

  printf 'ERROR: defenseclaw extension missing (%s)\n' "$index" >&2
  printf '  Fix: cd ~/src/defenseclaw && ./scripts/install.sh --yes --connector openclaw\n' >&2
  printf '  Or:  bash admin-access/heal-clawlab-stack.sh --fix\n' >&2
  return 1
}

ensure_clawlab_mcp_identity_extension() {
  local dest="${OPENCLAW_EXTENSIONS_DIR:-$HOME/.openclaw/extensions}/clawlab-mcp-identity"
  local repo="${CLAWLAB_REPO:-}"
  if [[ -z "$repo" ]]; then
    local here
    here="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
    repo="$here"
  fi
  local src="$repo/clawlab-extensions/clawlab-mcp-identity"
  if [[ -f "$dest/openclaw.plugin.json" ]]; then
    return 0
  fi
  [[ -d "$src" ]] || {
    printf 'WARN: missing clawlab-mcp-identity source: %s\n' "$src" >&2
    return 1
  }
  mkdir -p "$(dirname "$dest")"
  rm -rf "$dest"
  cp -a "$src" "$dest"
  printf '>> Installed clawlab-mcp-identity extension\n' >&2
  return 0
}

ensure_openclaw_extensions() {
  ensure_defenseclaw_openclaw_extension && ensure_clawlab_mcp_identity_extension
}

install_openclaw_ext_heal_units() {
  local repo="${CLAWLAB_REPO:-}"
  if [[ -z "$repo" ]]; then
    repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
  fi
  local unit_dir="${HOME}/.config/systemd/user"
  install -d -m 0755 "$unit_dir"
  install -m 0644 "$repo/systemd-user/openclaw-ext-heal.service" "$unit_dir/"
  install -m 0644 "$repo/systemd-user/openclaw-ext-heal.path" "$unit_dir/"
  systemctl --user daemon-reload
  systemctl --user enable --now openclaw-ext-heal.path 2>/dev/null \
    || systemctl --user enable openclaw-ext-heal.path 2>/dev/null || true
}
