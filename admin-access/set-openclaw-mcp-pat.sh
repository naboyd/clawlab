#!/usr/bin/env bash
# Set OpenClaw ssh-ops MCP auth to a personal access token (skops_…).
#
# Use when bookmarking /openclaw/chat URLs without clawBind from the portal hub.
# PAT provides proposer identity for propose_change without X-Claw-Mcp-Bind.
#
# Usage:
#   OPENCLAW_MCP_PAT=skops_xxx bash admin-access/set-openclaw-mcp-pat.sh
#   bash admin-access/set-openclaw-mcp-pat.sh   # prompts (hidden input)
set -Eeuo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib/mcp-proxy-env.sh
source "$REPO/admin-access/lib/mcp-proxy-env.sh"

OC_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"
CONFIG="$OC_HOME/openclaw.json"
VENV_PY="${CLAW_PYTHON:-$HOME/.clawlab/venv/bin/python}"
PROXY_BIND="${SSH_OPS_MCP_PROXY_BIND:-${SSH_OPS_MCP_PROXY_HOST:-127.0.0.1}}"
PROXY_URL="${SSH_OPS_MCP_PROXY_URL:-$(mcp_proxy_public_url "$PROXY_BIND")}"

[[ -f "$CONFIG" ]] || {
  echo "error: missing $CONFIG" >&2
  exit 1
}

pat="${OPENCLAW_MCP_PAT:-}"
if [[ -z "$pat" ]]; then
  read -r -s -p "Paste skops_ PAT from portal MCP tokens: " pat
  echo
fi
pat="${pat//$'\n'/}"
pat="${pat//$'\r'/}"
pat="${pat#Bearer }"
pat="${pat#bearer }"

if [[ ! "$pat" =~ ^skops_ ]]; then
  echo "error: expected token starting with skops_ (from portal hub → MCP tokens)" >&2
  exit 1
fi

"$VENV_PY" - "$CONFIG" "$PROXY_URL" "$pat" <<'PY'
import json, sys
from pathlib import Path

cfg_path, url, pat = sys.argv[1], sys.argv[2], sys.argv[3]
cfg = json.loads(Path(cfg_path).read_text())
entry = cfg.setdefault("mcp", {}).setdefault("servers", {}).setdefault("ssh-ops", {})
entry["url"] = url
entry["transport"] = "streamable-http"
entry["headers"] = {"Authorization": f"Bearer {pat}"}
Path(cfg_path).write_text(json.dumps(cfg, indent=2) + "\n")
print("Updated", cfg_path)
print("  mcp.servers.ssh-ops.url =", url)
print("  Authorization = Bearer skops_… (PAT)")
PY

echo "Restart: systemctl --user restart openclaw-gateway"
