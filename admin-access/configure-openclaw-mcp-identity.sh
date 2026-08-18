#!/usr/bin/env bash
# Point OpenClaw MCP at the identity proxy and enable the clawlab-mcp-identity plugin.
set -Eeuo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib/mcp-proxy-env.sh
source "$REPO/admin-access/lib/mcp-proxy-env.sh"

OC_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"
CONFIG="$OC_HOME/openclaw.json"
UNIT_DIR="$HOME/.config/systemd/user"
VENV_PY="${CLAW_PYTHON:-$HOME/.clawlab/venv/bin/python}"

if [[ ! -f "$CONFIG" ]]; then
  echo "Missing $CONFIG — run OpenClaw onboard first." >&2
  exit 1
fi

PYTHONPATH="$REPO/admin-access/lib" "$VENV_PY" "$REPO/admin-access/repair-openclaw-json.py" || exit 1

EXT_SRC="$REPO/clawlab-extensions/clawlab-mcp-identity"
EXT_DST="$OC_HOME/extensions/clawlab-mcp-identity"
mkdir -p "$OC_HOME/extensions"
rm -rf "$EXT_DST"
cp -a "$EXT_SRC" "$EXT_DST"

PROXY_BIND="${SSH_OPS_MCP_PROXY_BIND:-${SSH_OPS_MCP_PROXY_HOST:-127.0.0.1}}"
PROXY_URL="${SSH_OPS_MCP_PROXY_URL:-$(mcp_proxy_public_url "$PROXY_BIND")}"

"$VENV_PY" - <<PY
import sys
from pathlib import Path

sys.path.insert(0, "$REPO/admin-access/lib")
from openclaw_config import load_openclaw_json, save_openclaw_json

path = Path("$CONFIG")
cfg, _repaired = load_openclaw_json(path)
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
save_openclaw_json(path, cfg)
print("Updated", path)
print("  mcp.servers.ssh-ops.url =", mcp["url"])
PY

install -d -m 0755 "$UNIT_DIR"
install -m 0644 "$REPO/systemd-user/mcp-identity-proxy.service" "$UNIT_DIR/"

# Identity proxy runs on the same host as MCP; upstream is always loopback
# (podctl publishes 127.0.0.1:8766 regardless of quadlet PublishPort scrub IP).
MCP_UPSTREAM="${SSH_OPS_MCP_UPSTREAM_HOST:-127.0.0.1}"
SSH_OPS_DATA="${SSH_OPS_DATA:-$HOME/.clawlab/ssh-ops/data}"

mcp_proxy_write_dropin "$MCP_UPSTREAM" "$PROXY_BIND" "$SSH_OPS_DATA"

echo "  mcp-identity-proxy listen   = ${PROXY_BIND}:8767"
echo "  mcp-identity-proxy upstream = https://${MCP_UPSTREAM}:8766"
echo "  mcp-identity-proxy secrets  = ${SSH_OPS_DATA}"
if mcp_proxy_resolve_tls >/dev/null; then
  echo "  mcp-identity-proxy TLS      = lego ($(mcp_proxy_portal_domain))"
fi
if [[ "$PROXY_BIND" != "127.0.0.1" && "$PROXY_BIND" != "::1" ]] || mcp_proxy_resolve_tls >/dev/null; then
  echo "  Remote MCP URL (PAT skops_…): $(mcp_proxy_public_url "$PROXY_BIND")"
fi
rm -f "$UNIT_DIR/mcp-identity-proxy.service.d/upstream.conf"

systemctl --user daemon-reload
systemctl --user enable --now mcp-identity-proxy.service

echo "Restart OpenClaw gateway: systemctl --user restart openclaw-gateway"
echo "Open OpenClaw from the portal hub (link includes clawBind= for chat identity)."
echo "Bookmarked chat URLs: bash admin-access/set-openclaw-mcp-pat.sh  # skops_… PAT"
