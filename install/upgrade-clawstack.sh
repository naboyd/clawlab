#!/usr/bin/env bash
# =============================================================================
# upgrade-clawstack.sh — Pull clawlab + rebuild OpenClaw / DefenseClaw from source
# -----------------------------------------------------------------------------
# Mirrors install-clawstack.sh source-build paths:
#   ~/src/openclaw      → ~/.local/bin/openclaw
#   ~/src/defenseclaw   → defenseclaw CLI (via upstream install.sh)
#
# Usage:
#   bash install/upgrade-clawstack.sh
#   bash install/upgrade-clawstack.sh --restart          # restart local-full after upgrade
#   bash install/upgrade-clawstack.sh --force            # discard local changes in source trees
#   bash install/upgrade-clawstack.sh --skip-clawlab     # only OpenClaw + DefenseClaw
#   bash install/upgrade-clawstack.sh --skip-openclaw
#   bash install/upgrade-clawstack.sh --skip-defenseclaw
#   bash install/upgrade-clawstack.sh --rebuild-mcp      # podman rebuild ssh-ops image
#
# Safe to re-run; skips rebuild when upstream commit unchanged.
# =============================================================================
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib/clawlab-platform.sh
source "$SCRIPT_DIR/lib/clawlab-platform.sh"
# shellcheck source=lib/clawlab-local-full.sh
source "$SCRIPT_DIR/lib/clawlab-local-full.sh"
# shellcheck source=lib/clawlab-upgrade.sh
source "$SCRIPT_DIR/lib/clawlab-upgrade.sh"

clawlab_platform_init

REPO="$(clawlab_repo_root "$0")"
export CLAWLAB_REPO="$REPO"
SRC="${CLAWSTACK_SRC:-$HOME/src}"
BIN="$HOME/.local/bin"
OPENCLAW_SRC="$SRC/openclaw"
DEFENSECLAW_SRC="$SRC/defenseclaw"
OPENCLAW_URL="${OPENCLAW_GIT_URL:-https://github.com/openclaw/openclaw.git}"
DEFENSECLAW_URL="${DEFENSECLAW_GIT_URL:-https://github.com/cisco-ai-defense/defenseclaw.git}"

RESTART=0
FORCE=0
SKIP_CLAWLAB=0
SKIP_OPENCLAW=0
SKIP_DEFENSECLAW=0
REBUILD_MCP=0

log()  { printf '==> %s\n' "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*" >&2; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --restart) RESTART=1 ;;
    --force) FORCE=1 ;;
    --skip-clawlab) SKIP_CLAWLAB=1 ;;
    --skip-openclaw) SKIP_OPENCLAW=1 ;;
    --skip-defenseclaw) SKIP_DEFENSECLAW=1 ;;
    --rebuild-mcp) REBUILD_MCP=1 ;;
    -h|--help)
      sed -n '1,20p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) die "Unknown option: $1 (try --help)" ;;
  esac
  shift
done

[ "$(id -u)" -ne 0 ] || die "Run as your normal user, not root."

export PATH="$BIN:$PATH"
clawlab_prepend_openclaw_node_path || true

LOCAL_FULL=0
if clawlab_detect_local_full "$REPO"; then
  LOCAL_FULL=1
fi

pull_or_clone() {
  local dir="$1" url="$2" name="$3"
  local status

  if [[ ! -d "$dir/.git" ]]; then
    log "Cloning $name → $dir"
    mkdir -p "$(dirname "$dir")"
    git clone --depth 1 "$url" "$dir" || die "git clone failed for $name"
    info "$name @ $(upgrade_git_short "$dir") (fresh clone)"
    return 2
  fi

  if [[ "$FORCE" -eq 1 ]] && [[ -n "$(git -C "$dir" status --porcelain 2>/dev/null)" ]]; then
    warn "$name: discarding local changes (--force)"
    git -C "$dir" reset --hard HEAD >/dev/null 2>&1 || true
    git -C "$dir" clean -fd >/dev/null 2>&1 || true
  fi

  status="$(upgrade_git_check "$dir")"
  case "$status" in
    unchanged)
      info "$name @ $(upgrade_git_short "$dir") (already latest)"
      return 0
      ;;
    updated)
      info "$name @ $(upgrade_git_short "$dir") (pulled new commits)"
      return 2
      ;;
    dirty)
      warn "$name has local changes in $dir — commit, stash, or re-run with --force"
      return 1
      ;;
    fetch-failed)
      warn "$name: git fetch failed — check network and remote"
      return 1
      ;;
    missing)
      warn "$name: not a git repo at $dir"
      return 1
      ;;
    *)
      warn "$name: unexpected git status ($status)"
      return 1
      ;;
  esac
}

echo
log "ClawStack upgrade ($CLAWLAB_PLATFORM)"
info "clawlab repo: $REPO"
info "OpenClaw src:  $OPENCLAW_SRC"
info "DefenseClaw:   $DEFENSECLAW_SRC"
[[ "$LOCAL_FULL" -eq 1 ]] && info "local-full stack detected (use --restart to bounce services)"

CHANGED=0
NEED_OC_RESTART=0
NEED_DC_RESTART=0

# --- clawlab ---
if [[ "$SKIP_CLAWLAB" -eq 0 ]]; then
  log "clawlab git pull"
  if [[ -d "$REPO/.git" ]]; then
    if [[ "$FORCE" -eq 1 ]] && [[ -n "$(git -C "$REPO" status --porcelain 2>/dev/null)" ]]; then
      warn "clawlab: discarding local changes (--force)"
      git -C "$REPO" reset --hard HEAD >/dev/null 2>&1 || true
      git -C "$REPO" clean -fd >/dev/null 2>&1 || true
    fi
    before="$(upgrade_git_short "$REPO")"
    if [[ -n "$(git -C "$REPO" status --porcelain 2>/dev/null)" ]]; then
      warn "clawlab has uncommitted changes — skipping git pull (use --force to discard)"
    else
      branch="$(git -C "$REPO" rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)"
      git -C "$REPO" pull --ff-only origin "$branch" \
        && info "clawlab $before → $(upgrade_git_short "$REPO")" \
        && CHANGED=1 \
        || warn "clawlab git pull failed (merge conflict? resolve manually)"
    fi
  else
    warn "not a git checkout: $REPO — skipping clawlab pull"
  fi

  if [[ -f "$REPO/admin-access/install-clawlab-guardrail-rules.sh" ]]; then
    log "Refreshing Clawlab guardrail rules"
    bash "$REPO/admin-access/install-clawlab-guardrail-rules.sh" \
      || warn "guardrail rules refresh failed"
    NEED_DC_RESTART=1
  fi
fi

# --- OpenClaw ---
if [[ "$SKIP_OPENCLAW" -eq 0 ]]; then
  log "OpenClaw source check"
  oc_ver_before="$(openclaw --version 2>/dev/null | head -1 || true)"
  rc=0
  pull_or_clone "$OPENCLAW_SRC" "$OPENCLAW_URL" "OpenClaw" || rc=$?
  if [[ "$rc" -eq 2 ]]; then
    log "Building OpenClaw"
    upgrade_openclaw_build "$OPENCLAW_SRC" "$BIN" || die "OpenClaw build failed"
    CHANGED=1
    NEED_OC_RESTART=1
  fi
  oc_ver_after="$(openclaw --version 2>/dev/null | head -1 || true)"
  info "openclaw: ${oc_ver_before:-not installed} → ${oc_ver_after:-build failed}"
fi

# --- DefenseClaw ---
if [[ "$SKIP_DEFENSECLAW" -eq 0 ]]; then
  log "DefenseClaw source check"
  dc_ver_before="$(defenseclaw --version 2>/dev/null | head -1 || true)"
  rc=0
  pull_or_clone "$DEFENSECLAW_SRC" "$DEFENSECLAW_URL" "DefenseClaw" || rc=$?
  if [[ "$rc" -eq 2 ]]; then
    log "Reinstalling DefenseClaw from source"
    upgrade_defenseclaw_build "$DEFENSECLAW_SRC" "$BIN" || die "DefenseClaw install failed"
    CHANGED=1
    NEED_DC_RESTART=1
  fi
  dc_ver_after="$(defenseclaw --version 2>/dev/null | head -1 || true)"
  info "defenseclaw: ${dc_ver_before:-not installed} → ${dc_ver_after:-install failed}"
fi

# --- clawlab local-full extras ---
if [[ "$SKIP_CLAWLAB" -eq 0 && "$LOCAL_FULL" -eq 1 ]]; then
  log "Syncing local-full MCP + identity plugin"
  clawlab_local_full_ensure_hosts_inventory "$REPO" || true
  clawlab_local_full_register_mcp "$REPO" || true
  clawlab_local_full_configure_mcp_identity "$REPO" || true
  bash "$REPO/admin-access/install-clawlab-extras.sh" || true
fi

if [[ "$REBUILD_MCP" -eq 1 ]] && command -v podman >/dev/null 2>&1 \
  && [[ -x "$REPO/ssh-ops-mcp/podctl.sh" ]]; then
  log "Rebuilding ssh-ops Podman image"
  if [[ -f "$HOME/.claw-portals/config.env" ]] \
    && [[ -x "$REPO/admin-access/install-ssh-ops-mcp-quadlet.sh" ]]; then
    podman build -t ssh-ops:latest "$REPO/ssh-ops-mcp" \
      || warn "ssh-ops podman build failed"
    bash "$REPO/admin-access/install-ssh-ops-mcp-quadlet.sh" \
      || warn "ssh-ops-mcp quadlet refresh failed"
  else
    CLAWLAB_MANAGE_MCP=1 SSH_OPS_DIR="$REPO/ssh-ops-mcp" bash "$REPO/ssh-ops-mcp/podctl.sh" --build --recreate \
      || warn "ssh-ops podman rebuild failed"
  fi
  CHANGED=1
fi

# --- service restarts ---
if [[ "$NEED_DC_RESTART" -eq 1 ]] && command -v defenseclaw-gateway >/dev/null 2>&1; then
  log "Restarting DefenseClaw gateway (rules or binary changed)"
  defenseclaw-gateway restart >/dev/null 2>&1 \
    || warn "defenseclaw-gateway restart failed — run manually"
fi

if [[ "$RESTART" -eq 1 && "$LOCAL_FULL" -eq 1 ]]; then
  log "Restarting local-full stack"
  bash "$REPO/install/local-full-ctl.sh" restart || warn "local-full-ctl restart failed"
elif [[ "$NEED_OC_RESTART" -eq 1 && "$LOCAL_FULL" -eq 1 ]]; then
  warn "OpenClaw updated — restart gateway: bash $REPO/install/local-full-ctl.sh restart"
fi

echo
if [[ "$CHANGED" -eq 0 ]]; then
  log "Nothing to upgrade — all sources already at latest commits"
else
  log "Upgrade complete"
fi
info "Verify: openclaw --version  ·  defenseclaw --version  ·  defenseclaw guardrail status"
[[ "$LOCAL_FULL" -eq 1 ]] && info "Portal:  bash $REPO/install/local-full-ctl.sh status"
[[ "$LOCAL_FULL" -eq 1 ]] && info "Policy:  cd $REPO/tests && ./policy-test.sh --no-agent"
