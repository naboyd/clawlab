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
PROXY_BIND="$(mcp_proxy_resolve_bind)"
PROXY_URL="${SSH_OPS_MCP_GATEWAY_URL:-${SSH_OPS_MCP_PROXY_URL:-$(mcp_proxy_gateway_url "$PROXY_BIND")}}"

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

"$VENV_PY" - "$REPO" "$CONFIG" "$PROXY_URL" "$pat" <<'PY'
import sys
from pathlib import Path

repo, cfg_path, url, pat = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4]
sys.path.insert(0, str(Path(repo) / "admin-access" / "lib"))
from openclaw_config import load_openclaw_json, save_openclaw_json

cfg, _repaired = load_openclaw_json(cfg_path)
entry = cfg.setdefault("mcp", {}).setdefault("servers", {}).setdefault("ssh-ops", {})
entry["url"] = url
entry["transport"] = "streamable-http"
entry["headers"] = {"Authorization": f"Bearer {pat}"}
save_openclaw_json(cfg_path, cfg)
print("Updated", cfg_path)
print("  mcp.servers.ssh-ops.url =", url)
print("  Authorization = Bearer skops_… (PAT)")
PY

echo "Restart: systemctl --user restart openclaw-gateway"
