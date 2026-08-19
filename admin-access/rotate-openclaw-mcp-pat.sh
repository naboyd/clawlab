#!/usr/bin/env bash
# Issue a fresh skops_ PAT and install it in ~/.openclaw/openclaw.json for OpenClaw.
#
# Use when rotating OpenClaw MCP identity (bookmark URLs) or recovering from a leaked PAT.
# Prefer portal hub → Open OpenClaw ↗ (clawBind) when possible — no PAT stored on disk.
#
# Usage:
#   bash admin-access/rotate-openclaw-mcp-pat.sh
#   bash admin-access/rotate-openclaw-mcp-pat.sh --user alice --label openclaw-gateway
#   bash admin-access/rotate-openclaw-mcp-pat.sh --no-revoke-old --no-restart
set -Eeuo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PY="${CLAW_PYTHON:-$HOME/.clawlab/venv/bin/python}"
[[ -x "$VENV_PY" ]] || VENV_PY=python3

USER_NAME="${CLAW_AUTH_USER:-${USER:-}}"
LABEL="${OPENCLAW_MCP_PAT_LABEL:-openclaw-gateway}"
TTL_DAYS=""
REVOKE_OLD=1
APPLY=1
RESTART=1

usage() {
  sed -n '3,12p' "$0" | sed 's/^# \{0,1\}//'
  echo "Options:"
  echo "  --user NAME       claw-auth user (default: \$USER)"
  echo "  --label LABEL     PAT label in hub (default: openclaw-gateway)"
  echo "  --ttl-days N      optional expiry"
  echo "  --no-revoke-old   keep other active PATs with the same label"
  echo "  --no-apply        issue only; do not write openclaw.json"
  echo "  --no-restart      skip systemctl --user restart openclaw-gateway"
  echo "  -h, --help"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --user) USER_NAME="$2"; shift 2 ;;
    --label) LABEL="$2"; shift 2 ;;
    --ttl-days) TTL_DAYS="$2"; shift 2 ;;
    --no-revoke-old) REVOKE_OLD=0; shift ;;
    --no-apply) APPLY=0; shift ;;
    --no-restart) RESTART=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "error: unknown option: $1" >&2; usage >&2; exit 1 ;;
  esac
done

[[ -n "$USER_NAME" ]] || {
  echo "error: set --user or CLAW_AUTH_USER" >&2
  exit 1
}

export CLAW_AUTH_DB="${CLAW_AUTH_DB:-$HOME/.claw-auth/users.db}"
export PYTHONPATH="${REPO}/admin-access/lib:${REPO}/ssh-ops-mcp${PYTHONPATH:+:$PYTHONPATH}"

RESULT="$(
  REPO_ROOT="$REPO" REVOKE_OLD="$REVOKE_OLD" APPLY="$APPLY" RESTART="$RESTART" \
  TTL_DAYS="$TTL_DAYS" LABEL="$LABEL" USER_NAME="$USER_NAME" \
  "$VENV_PY" - <<'PY'
import os, sys
from pathlib import Path

repo = Path(os.environ["REPO_ROOT"])
sys.path[:0] = [str(repo / "admin-access" / "lib"), str(repo / "ssh-ops-mcp")]

from openclaw_mcp_pat import issue_pat_for_openclaw, resolve_gateway_mcp_url, restart_openclaw_gateway

user = os.environ["USER_NAME"].strip().lower()
label = os.environ["LABEL"]
ttl_raw = os.environ.get("TTL_DAYS", "").strip()
ttl = int(ttl_raw) if ttl_raw else None
revoke = os.environ.get("REVOKE_OLD", "1") not in ("0", "false", "no")
apply = os.environ.get("APPLY", "1") not in ("0", "false", "no")
do_restart = os.environ.get("RESTART", "1") not in ("0", "false", "no")

raw, cfg_path = issue_pat_for_openclaw(
    user, label=label, ttl_days=ttl, revoke_label_first=revoke, apply_openclaw=apply,
)
print("TOKEN", raw)
if cfg_path:
    print("CFG", cfg_path, resolve_gateway_mcp_url())
if apply and do_restart:
    ok, detail = restart_openclaw_gateway()
    print("GW", "ok" if ok else detail)
PY
)" || {
  echo "error: failed to issue PAT" >&2
  printf '%s\n' "$RESULT" >&2
  exit 1
}

TOKEN="$(printf '%s\n' "$RESULT" | awk '/^TOKEN /{print $2}')"
CFG_LINE="$(printf '%s\n' "$RESULT" | awk '/^CFG /{print $0}')"
GW_LINE="$(printf '%s\n' "$RESULT" | awk '/^GW /{print $0}')"

[[ -n "$TOKEN" ]] || {
  echo "error: no token returned (check CLAW_AUTH_DB and username)" >&2
  exit 1
}

echo "Issued PAT for ${USER_NAME} (label=${LABEL})"
echo "  prefix: ${TOKEN:0:12}… — copy the full token below (shown once)"
echo ""
echo "$TOKEN"
echo ""
if [[ -n "$CFG_LINE" ]]; then
  echo "Updated $(echo "$CFG_LINE" | awk '{print $2}')"
  echo "  mcp.servers.ssh-ops.url = $(echo "$CFG_LINE" | awk '{print $3}')"
  echo "  Authorization = Bearer skops_…"
fi
if [[ -n "$GW_LINE" ]]; then
  status="$(echo "$GW_LINE" | cut -d' ' -f2-)"
  if [[ "$status" == "ok" ]]; then
    echo "Restarted openclaw-gateway"
  else
    echo "WARN: gateway restart: $status"
    echo "  Run: systemctl --user restart openclaw-gateway"
  fi
elif [[ "$APPLY" -eq 1 && "$RESTART" -eq 0 ]]; then
  echo "Restart: systemctl --user restart openclaw-gateway"
fi
