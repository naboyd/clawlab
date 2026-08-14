#!/usr/bin/env bash
# Sync OpenClaw gateway token files + ssh-ops MCP bearer in openclaw.json, then restart services.
set -Eeuo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
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
SSH_OPS_CONFIG="$DATA_DIR/hosts.yaml" \
SSH_OPS_ENV="$DATA_DIR/.env" \
SSH_OPS_KEYFILE="$DATA_DIR/master.key" \
PYTHONPATH="$REPO/ssh-ops-mcp" \
  "$VENV_PY" - <<'PY'
import json, os, sys
from pathlib import Path
import secrets_store

oc = Path(os.environ.get("OPENCLAW_HOME", Path.home() / ".openclaw")) / "openclaw.json"
token = secrets_store.ensure_mcp_token()
cfg = json.loads(oc.read_text())
entry = cfg.setdefault("mcp", {}).setdefault("servers", {}).setdefault("ssh-ops", {})
entry["url"] = os.environ.get("SSH_OPS_MCP_PROXY_URL", "http://127.0.0.1:8767/mcp")
entry["transport"] = "streamable-http"
entry["headers"] = {"Authorization": f"Bearer {token}"}
oc.write_text(json.dumps(cfg, indent=2) + "\n")
print("openclaw.json ssh-ops MCP auth synced")
PY

# Identity proxy must reach MCP on loopback (podman publishes 127.0.0.1:8766).
OVERRIDE_DIR="$HOME/.config/systemd/user/mcp-identity-proxy.service.d"
mkdir -p "$OVERRIDE_DIR"
cat >"$OVERRIDE_DIR/upstream.conf" <<'EOF'
[Service]
Environment=SSH_OPS_MCP_UPSTREAM=https://127.0.0.1:8766
EOF
say "Identity proxy upstream -> https://127.0.0.1:8766"

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
