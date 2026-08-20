#!/usr/bin/env bash
# Register Cisco ThousandEyes hosted MCP in OpenClaw (streamable HTTP + Bearer token).
#
# Token is stored in ~/.clawlab/thousandeyes/env (mode 600) and copied into
# openclaw.json headers — same pattern as set-openclaw-mcp-pat.sh for ssh-ops.
#
# Usage:
#   THOUSANDEYES_API_TOKEN=… bash admin-access/configure-openclaw-thousandeyes-mcp.sh
#   bash admin-access/configure-openclaw-thousandeyes-mcp.sh   # prompts (hidden)
#   bash admin-access/configure-openclaw-thousandeyes-mcp.sh --remove
set -Eeuo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
OC_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"
CONFIG="$OC_HOME/openclaw.json"
VENV_PY="${CLAW_PYTHON:-$HOME/.clawlab/venv/bin/python}"
TE_DIR="${CLAWLAB_THOUSANDEYES_DIR:-$HOME/.clawlab/thousandeyes}"
TE_ENV="$TE_DIR/env"
TE_MCP_URL="${THOUSANDEYES_MCP_URL:-https://api.thousandeyes.com/mcp}"
REMOVE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --remove) REMOVE=1 ;;
    -h|--help)
      sed -n '1,14p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
  shift
done

[[ -f "$CONFIG" ]] || {
  echo "error: missing $CONFIG — run install-clawstack first" >&2
  exit 1
}

if [[ "$REMOVE" -eq 1 ]]; then
  "$VENV_PY" - "$REPO" "$CONFIG" <<'PY'
import sys
from pathlib import Path

repo, cfg_path = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(repo / "admin-access" / "lib"))
from openclaw_config import load_openclaw_json, save_openclaw_json

cfg, _ = load_openclaw_json(cfg_path)
servers = (cfg.get("mcp") or {}).get("servers") or {}
if "thousandeyes" in servers:
    del servers["thousandeyes"]
    save_openclaw_json(cfg_path, cfg)
    print("Removed mcp.servers.thousandeyes from", cfg_path)
else:
    print("No thousandeyes MCP entry in", cfg_path)
PY
  echo "Restart: systemctl --user restart openclaw-gateway"
  exit 0
fi

token="${THOUSANDEYES_API_TOKEN:-}"
if [[ -z "$token" && -f "$TE_ENV" ]]; then
  # shellcheck disable=SC1090
  set -a
  source "$TE_ENV"
  set +a
  token="${THOUSANDEYES_API_TOKEN:-}"
fi

if [[ -z "$token" ]]; then
  read -r -s -p "Paste ThousandEyes API token (Account Settings → Users → API Access): " token
  echo
fi

token="${token//$'\n'/}"
token="${token//$'\r'/}"
token="${token#Bearer }"
token="${token#bearer }"

if [[ ${#token} -lt 16 ]]; then
  echo "error: token looks too short — check ThousandEyes API token" >&2
  exit 1
fi

mkdir -p "$TE_DIR"
chmod 700 "$TE_DIR"
printf 'THOUSANDEYES_API_TOKEN=%s\n' "$token" > "$TE_ENV"
chmod 600 "$TE_ENV"

"$VENV_PY" - "$REPO" "$CONFIG" "$TE_MCP_URL" "$token" <<'PY'
import sys
from pathlib import Path

repo, cfg_path, url, token = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4]
sys.path.insert(0, str(Path(repo) / "admin-access" / "lib"))
from openclaw_config import load_openclaw_json, save_openclaw_json

cfg, _repaired = load_openclaw_json(cfg_path)
entry = cfg.setdefault("mcp", {}).setdefault("servers", {}).setdefault("thousandeyes", {})
entry["url"] = url
entry["transport"] = "streamable-http"
entry["headers"] = {"Authorization": f"Bearer {token}"}
save_openclaw_json(cfg_path, cfg)
print("Updated", cfg_path)
print("  mcp.servers.thousandeyes.url =", url)
print("  Authorization = Bearer … (ThousandEyes API token)")
print("  token file:", Path.home() / ".clawlab" / "thousandeyes" / "env")
PY

bash "$REPO/admin-access/install-clawlab-skills.sh" >/dev/null 2>&1 || true

echo
echo "ThousandEyes MCP registered. Restart OpenClaw gateway:"
echo "  systemctl --user restart openclaw-gateway"
echo "  # or: bash install/local-full-ctl.sh restart"
