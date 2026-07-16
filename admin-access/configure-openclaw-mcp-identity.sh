#!/usr/bin/env bash
# Point OpenClaw MCP at the identity proxy and enable the clawlab-mcp-identity plugin.
set -Eeuo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
OC_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"
CONFIG="$OC_HOME/openclaw.json"
UNIT_DIR="$HOME/.config/systemd/user"
VENV_PY="${CLAW_PYTHON:-$HOME/.clawlab/venv/bin/python}"

if [[ ! -f "$CONFIG" ]]; then
  echo "Missing $CONFIG — run OpenClaw onboard first." >&2
  exit 1
fi

EXT_SRC="$REPO/clawlab-extensions/clawlab-mcp-identity"
EXT_DST="$OC_HOME/extensions/clawlab-mcp-identity"
mkdir -p "$OC_HOME/extensions"
rm -rf "$EXT_DST"
cp -a "$EXT_SRC" "$EXT_DST"

PROXY_URL="${SSH_OPS_MCP_PROXY_URL:-http://127.0.0.1:8767/mcp}"
"$VENV_PY" - <<PY
import json
from pathlib import Path

cfg = json.loads(Path("$CONFIG").read_text())
mcp = cfg.setdefault("mcp", {}).setdefault("servers", {}).setdefault("ssh-ops", {})
mcp["url"] = "$PROXY_URL"
mcp.setdefault("transport", "streamable-http")
plugins = cfg.setdefault("plugins", {})
allow = list(plugins.setdefault("allow", []))
if "clawlab-mcp-identity" not in allow:
    allow.append("clawlab-mcp-identity")
plugins["allow"] = allow
entries = plugins.setdefault("entries", {})
entries.setdefault("clawlab-mcp-identity", {})["enabled"] = True
load = plugins.setdefault("load", {})
paths = list(load.setdefault("paths", []))
ext = "$EXT_DST"
if ext not in paths:
    paths.append(ext)
load["paths"] = paths
Path("$CONFIG").write_text(json.dumps(cfg, indent=2) + "\n")
print("Updated", "$CONFIG")
print("  mcp.servers.ssh-ops.url =", mcp["url"])
PY

install -d -m 0755 "$UNIT_DIR"
install -m 0644 "$REPO/systemd-user/mcp-identity-proxy.service" "$UNIT_DIR/"

# Upstream MCP listens on the podman bridge IP (see quadlets/ssh-ops-mcp.container PublishPort).
MCP_HOST="${SSH_OPS_MCP_HOST:-}"
if [[ -z "$MCP_HOST" && -f "$REPO/quadlets/ssh-ops-mcp.container" ]]; then
  MCP_HOST="$(grep -E '^PublishPort=' "$REPO/quadlets/ssh-ops-mcp.container" \
    | head -1 | sed -E 's/.*PublishPort=([^:]+):8766.*/\1/')"
fi
MCP_HOST="${MCP_HOST:-192.168.128.93}"
OVERRIDE_DIR="$UNIT_DIR/mcp-identity-proxy.service.d"
install -d -m 0755 "$OVERRIDE_DIR"
cat >"$OVERRIDE_DIR/upstream.conf" <<EOF
[Service]
Environment=SSH_OPS_MCP_UPSTREAM=https://${MCP_HOST}:8766
EOF
echo "  mcp-identity-proxy upstream = https://${MCP_HOST}:8766"

systemctl --user daemon-reload
systemctl --user enable --now mcp-identity-proxy.service

echo "Restart OpenClaw gateway: systemctl --user restart openclaw-gateway"
echo "Open OpenClaw from the portal hub (link includes clawBind= for chat identity)."
