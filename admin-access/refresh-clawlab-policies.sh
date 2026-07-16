#!/usr/bin/env bash
# Refresh Clawlab policy YAML from the repo and reload dependent services.
#
# Use after git pull when policy templates changed, or when runtime copies under
# ~/.ssh_ops_mcp/data/ are stale (e.g. ssh-ops Policy tab shows too few groups).
#
# Usage:
#   bash admin-access/refresh-clawlab-policies.sh
#   bash admin-access/refresh-clawlab-policies.sh --preserve-access
#   bash admin-access/refresh-clawlab-policies.sh --pull --rebuild-ssh-ops
#   bash admin-access/refresh-clawlab-policies.sh --no-restart
#
# Options:
#   --pull              git pull --ff-only in the repo first
#   --preserve-access   keep per-group access modes from runtime ios-xe-policy.yaml
#   --rebuild-ssh-ops   podman build ssh-ops:latest and restart ssh-ops-gui
#   --no-restart        sync files only (no systemctl / defenseclaw-gateway)
#   --dry-run           show actions without writing or restarting
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${CLAW_PYTHON:-python3}"
VENV="${CLAWLAB_VENV:-$HOME/.clawlab/venv}"
if [[ -x "$VENV/bin/python" ]]; then
  PY="$VENV/bin/python"
fi

DO_PULL=0
PRESERVE_ACCESS=0
REBUILD_SSH_OPS=0
NO_RESTART=0
DRY_RUN=0

for arg in "$@"; do
  case "$arg" in
    --pull) DO_PULL=1 ;;
    --preserve-access) PRESERVE_ACCESS=1 ;;
    --rebuild-ssh-ops) REBUILD_SSH_OPS=1 ;;
    --no-restart) NO_RESTART=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help)
      sed -n '2,18p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      exit 2
      ;;
  esac
done

run() {
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "DRY-RUN: $*"
  else
    echo "==> $*"
    "$@"
  fi
}

echo "=============================================="
echo " Clawlab policy refresh"
echo " repo: $REPO"
echo " host: $(hostname -f 2>/dev/null || hostname)"
echo " time: $(date '+%Y-%m-%dT%H:%M:%S%z' 2>/dev/null || date)"
echo "=============================================="
echo

if [[ "$DO_PULL" == "1" ]]; then
  run git -C "$REPO" pull --ff-only
  echo
fi

echo "==> Regenerate ios-xe-policy.yaml from generator"
if [[ "$DRY_RUN" == "1" ]]; then
  echo "DRY-RUN: $PY admin-access/sync-ios-xe-policy.py"
else
  "$PY" "${REPO}/admin-access/sync-ios-xe-policy.py"
fi
echo

echo "==> Deploy ios-xe-policy.yaml to runtime paths"
DEPLOY_ARGS=()
[[ "$PRESERVE_ACCESS" == "1" ]] && DEPLOY_ARGS+=(--preserve-access)
[[ "$DRY_RUN" == "1" ]] && DEPLOY_ARGS+=(--dry-run)
"$PY" "${REPO}/admin-access/deploy-ios-xe-policy.py" "${DEPLOY_ARGS[@]}"
echo

echo "==> Merge guardrail + IOS-XE rules into DefenseClaw rule pack"
if [[ "$DRY_RUN" == "1" ]]; then
  echo "DRY-RUN: bash admin-access/install-clawlab-guardrail-rules.sh"
else
  bash "${REPO}/admin-access/install-clawlab-guardrail-rules.sh"
fi
echo

echo "==> Sync OpenClaw MCP identity plugin"
if [[ "$DRY_RUN" == "1" ]]; then
  echo "DRY-RUN: bash admin-access/configure-openclaw-mcp-identity.sh"
else
  bash "${REPO}/admin-access/configure-openclaw-mcp-identity.sh"
fi
echo

if [[ "$REBUILD_SSH_OPS" == "1" ]] && command -v podman >/dev/null 2>&1; then
  echo "==> Rebuild ssh-ops container image"
  run podman build -t ssh-ops:latest "${REPO}/ssh-ops-mcp"
  echo
elif [[ "$REBUILD_SSH_OPS" == "1" ]]; then
  echo "WARN: podman not found — skipping ssh-ops image rebuild"
  echo
fi

if [[ "$NO_RESTART" == "1" ]]; then
  echo "Done (no service restarts; --no-restart)."
  exit 0
fi

echo "==> Restart user services"
RESTART=(defenseclaw-webgui ssh-ops-gui)
if [[ "$DRY_RUN" != "1" ]]; then
  systemctl --user restart "${RESTART[@]}" 2>/dev/null || true
  sleep 2
  for unit in "${RESTART[@]}"; do
    if systemctl --user is-active --quiet "${unit}.service" 2>/dev/null; then
      echo "  OK: ${unit} active"
    else
      echo "  WARN: ${unit} not active (may not be installed)"
    fi
  done
  if command -v defenseclaw-gateway >/dev/null 2>&1; then
    defenseclaw-gateway restart 2>/dev/null && echo "  OK: defenseclaw-gateway restarted" \
      || echo "  WARN: defenseclaw-gateway restart failed"
  fi
else
  echo "DRY-RUN: systemctl --user restart ${RESTART[*]}"
  echo "DRY-RUN: defenseclaw-gateway restart"
fi

echo
echo "Done. Verify:"
echo "  ssh-ops Policy tab — expect ~60 IOS-XE groups"
echo "  DefenseClaw IOS-XE tab — ${REPO}/config-templates/ios-xe-policy.yaml"
echo "  ./tests/test_ios_xe_policy_groups.py"
echo
echo "OpenClaw gateway is NOT restarted (avoids unnecessary Control UI downtime)."
echo "  systemctl --user restart openclaw-gateway   # only if needed"
