#!/usr/bin/env bash
# Sync OpenClaw gateway token files + ssh-ops MCP bearer in openclaw.json, then restart services.
#
# MCP auth model (see admin-access/configure-portal-mcp-auth.sh):
#   • OpenClaw + portal hub: clawBind via clawlab-mcp-identity (no PAT required)
#   • OpenClaw + bookmarked chat URL: set-openclaw-mcp-pat.sh (skops_…)
#   • This script: shared bearer + :8767 identity proxy URL (machine auth to proxy)
#   • Cursor / external: portal MCP tokens → skops_… on :8767 (never :8766 direct)
set -Eeuo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib/mcp-proxy-env.sh
source "$REPO/admin-access/lib/mcp-proxy-env.sh"
OC_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"
DATA_DIR="${SSH_OPS_DATA:-$HOME/.clawlab/ssh-ops/data}"
VENV_PY="${CLAW_PYTHON:-$HOME/.clawlab/venv/bin/python}"

say() { printf '>> %s\n' "$*"; }

[[ -f "$OC_HOME/openclaw.json" ]] || {
  echo "error: missing $OC_HOME/openclaw.json" >&2
  exit 1
}

say "Syncing gateway token (.env <-> gateway.systemd.env + SecretRef in openclaw.json)"
DOMAIN="${DOMAIN:-icecream.naboydciscolab.com}" \
PORT_PORTAL="${PORT_PORTAL:-8443}" \
SCHEME="${SCHEME:-https}" \
  python3 "$REPO/admin-access/apply-token-portal.py"

say "Syncing gateway token -> DefenseClaw (.env + shims/.token)"
python3 <<'PY'
import os
from pathlib import Path

TOKEN_ENV = "OPENCLAW_GATEWAY_TOKEN"
DC_TOKEN_ENV = "DEFENSECLAW_GATEWAY_TOKEN"
home = Path.home()

def read_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip("\"'")
    return out

def upsert(path: Path, key: str, val: str) -> None:
    lines: list[str] = []
    found = False
    if path.is_file():
        for line in path.read_text().splitlines():
            if line.startswith(f"{key}="):
                lines.append(f"{key}={val}")
                found = True
            else:
                lines.append(line)
    if not found:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"{key}={val}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n")
    os.chmod(path, 0o600)

canonical = read_env(home / ".openclaw/gateway.systemd.env").get(TOKEN_ENV) or read_env(
    home / ".openclaw/.env"
).get(TOKEN_ENV)
if not canonical:
    raise SystemExit("error: no OPENCLAW_GATEWAY_TOKEN in ~/.openclaw env files")

for target in (
    home / ".defenseclaw/.env",
    home / ".defenseclaw/shims/.token",
):
    upsert(target, TOKEN_ENV, canonical)
    upsert(target, DC_TOKEN_ENV, canonical)
    print(f"synced {target.name}")

print("DefenseClaw gateway tokens synced")
PY

say "Syncing ssh-ops MCP bearer from secrets store -> openclaw.json"
REPO_EXT="$REPO/clawlab-extensions/clawlab-mcp-identity"
OC_EXT="$OC_HOME/extensions/clawlab-mcp-identity"
if [[ -d "$REPO_EXT" && ! -f "$OC_EXT/openclaw.plugin.json" ]]; then
  say "Installing missing clawlab-mcp-identity extension (gateway requires this path)"
  mkdir -p "$OC_HOME/extensions"
  rm -rf "$OC_EXT"
  cp -a "$REPO_EXT" "$OC_EXT"
fi
UNIT_DIR="$HOME/.config/systemd/user"
OVERRIDE_DIR="$UNIT_DIR/mcp-identity-proxy.service.d"
PROXY_BIND="${SSH_OPS_MCP_PROXY_BIND:-${SSH_OPS_MCP_PROXY_HOST:-}}"
if [[ -z "$PROXY_BIND" && -f "$OVERRIDE_DIR/clawlab.conf" ]]; then
  PROXY_BIND="$(grep -E '^Environment=SSH_OPS_MCP_PROXY_HOST=' "$OVERRIDE_DIR/clawlab.conf" \
    | head -1 | sed 's/^Environment=SSH_OPS_MCP_PROXY_HOST=//' || true)"
fi
PROXY_BIND="${PROXY_BIND:-127.0.0.1}"
PROXY_URL="${SSH_OPS_MCP_PROXY_URL:-$(mcp_proxy_public_url "$PROXY_BIND")}"
SSH_OPS_CONFIG="$DATA_DIR/hosts.yaml" \
SSH_OPS_ENV="$DATA_DIR/.env" \
SSH_OPS_KEYFILE="$DATA_DIR/master.key" \
SSH_OPS_MCP_PROXY_URL="$PROXY_URL" \
PYTHONPATH="$REPO/ssh-ops-mcp" \
  "$VENV_PY" - <<PY
import json, os, sys
from pathlib import Path

sys.path.insert(0, "$REPO/admin-access/lib")
import secrets_store
from openclaw_config import load_openclaw_json, save_openclaw_json

oc = Path(os.environ.get("OPENCLAW_HOME", Path.home() / ".openclaw")) / "openclaw.json"
token = secrets_store.ensure_mcp_token()
cfg, _repaired = load_openclaw_json(oc)
entry = cfg.setdefault("mcp", {}).setdefault("servers", {}).setdefault("ssh-ops", {})
entry["url"] = os.environ.get("SSH_OPS_MCP_PROXY_URL", "http://127.0.0.1:8767/mcp")
entry["transport"] = "streamable-http"
entry["headers"] = {"Authorization": f"Bearer {token}"}
save_openclaw_json(oc, cfg)
print("openclaw.json ssh-ops MCP auth synced")
PY

# Identity proxy: same data dir + upstream as the MCP container (podctl.sh).
install -d -m 0755 "$UNIT_DIR" "$OVERRIDE_DIR"
install -m 0644 "$REPO/systemd-user/mcp-identity-proxy.service" "$UNIT_DIR/"
mcp_proxy_write_dropin "127.0.0.1" "$PROXY_BIND" "$DATA_DIR"
rm -f "$OVERRIDE_DIR/upstream.conf"
say "Identity proxy listen ${PROXY_BIND}:8767 -> upstream :8766, secrets ${DATA_DIR}"
if mcp_proxy_resolve_tls >/dev/null; then
  say "Identity proxy TLS: lego cert for $(mcp_proxy_portal_domain)"
fi

systemctl --user daemon-reload
systemctl --user restart mcp-identity-proxy.service openclaw-gateway.service
DC_GW="${DEFENSECLAW_GATEWAY_BIN:-$HOME/.local/bin/defenseclaw-gateway}"
if [[ -x "$DC_GW" ]]; then
  "$DC_GW" restart || say "WARN: defenseclaw-gateway restart failed"
elif command -v defenseclaw-gateway >/dev/null 2>&1; then
  defenseclaw-gateway restart || say "WARN: defenseclaw-gateway restart failed"
else
  say "WARN: defenseclaw-gateway not found — restart manually"
fi

say "Restarted mcp-identity-proxy + openclaw-gateway + defenseclaw-gateway"
say "Check: journalctl --user -u openclaw-gateway.service -n 20 | grep token_mismatch"
say "Check: tail -5 ~/.defenseclaw/gateway.log"
