"""Issue MCP PATs and install them in ~/.openclaw/openclaw.json for OpenClaw gateway."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SSH_OPS = _REPO / "ssh-ops-mcp"
if str(_SSH_OPS) not in sys.path:
    sys.path.insert(0, str(_SSH_OPS))

import mcp_tokens  # noqa: E402

from openclaw_config import (  # noqa: E402
    default_config_path,
    load_openclaw_json,
    save_openclaw_json,
)


def resolve_gateway_mcp_url() -> str:
    """Match admin-access/lib/mcp-proxy-env.sh mcp_proxy_gateway_url()."""
    override = os.environ.get("SSH_OPS_MCP_GATEWAY_URL") or os.environ.get(
        "SSH_OPS_MCP_PROXY_URL"
    )
    if override:
        return override.strip()

    portal_env = Path(
        os.environ.get("CLAW_PORTAL_ENV", Path.home() / ".claw-portals" / "config.env")
    ).expanduser()
    lan_ip = "127.0.0.1"
    domain = ""
    if portal_env.is_file():
        for line in portal_env.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            val = val.strip().strip("\"'")
            if key == "LAN_IP":
                lan_ip = val or lan_ip
            elif key == "DOMAIN":
                domain = val

    bind = os.environ.get("SSH_OPS_MCP_PROXY_BIND") or os.environ.get(
        "SSH_OPS_MCP_PROXY_HOST"
    )
    if not bind:
        dropin = (
            Path.home()
            / ".config/systemd/user/mcp-identity-proxy.service.d/clawlab.conf"
        )
        if dropin.is_file():
            for line in dropin.read_text().splitlines():
                if line.startswith("Environment=SSH_OPS_MCP_PROXY_HOST="):
                    bind = line.split("=", 1)[1].strip()
                    break
    bind = bind or lan_ip

    lego = Path(
        os.environ.get(
            "SSH_OPS_MCP_TLS_DIR",
            Path.home() / "mcp/acme/lego/certificates",
        )
    ).expanduser()
    scheme = "http"
    if domain and (lego / f"{domain}.crt").is_file() and (lego / f"{domain}.key").is_file():
        scheme = "https"

    if scheme == "https" and domain:
        return f"https://{domain}:8767/mcp"
    if bind not in ("127.0.0.1", "::1"):
        return f"{scheme}://{bind}:8767/mcp"
    return f"{scheme}://127.0.0.1:8767/mcp"


def apply_pat_to_openclaw(
    pat: str,
    *,
    proxy_url: str | None = None,
    config_path: Path | None = None,
) -> Path:
    """Write skops_ PAT + MCP proxy URL into openclaw.json."""
    raw = (pat or "").strip()
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    if not raw.startswith(mcp_tokens.PAT_PREFIX):
        raise ValueError("expected PAT starting with skops_")

    cfg_path = config_path or default_config_path()
    url = proxy_url or resolve_gateway_mcp_url()
    cfg, _repaired = load_openclaw_json(cfg_path)
    entry = cfg.setdefault("mcp", {}).setdefault("servers", {}).setdefault("ssh-ops", {})
    entry["url"] = url
    entry["transport"] = "streamable-http"
    entry["headers"] = {"Authorization": f"Bearer {raw}"}
    save_openclaw_json(cfg_path, cfg)
    return cfg_path


def revoke_active_pats(
    username: str,
    *,
    label: str | None = None,
    actor: str | None = None,
    is_superadmin: bool = False,
) -> int:
    """Revoke active PATs for user; optional exact label filter. Returns count revoked."""
    username = username.strip().lower()
    actor = (actor or username).strip().lower()
    revoked = 0
    for row in mcp_tokens.list_pats(username):
        if row.get("revoked"):
            continue
        if label is not None and (row.get("label") or "") != label:
            continue
        mcp_tokens.revoke_pat(int(row["id"]), actor=actor, is_superadmin=is_superadmin)
        revoked += 1
    return revoked


def issue_pat_for_openclaw(
    username: str,
    *,
    label: str = "openclaw-gateway",
    ttl_days: int | None = None,
    revoke_label_first: bool = True,
    apply_openclaw: bool = True,
    actor: str | None = None,
    is_superadmin: bool = False,
) -> tuple[str, Path | None]:
    """
    Issue PAT, optionally revoke prior tokens with the same label, optionally write openclaw.json.
    Returns (raw_token, config_path or None).
    """
    username = username.strip().lower()
    if revoke_label_first:
        revoke_active_pats(
            username,
            label=label,
            actor=actor or username,
            is_superadmin=is_superadmin,
        )
    raw = mcp_tokens.issue_pat(username, label, ttl_days=ttl_days)
    cfg_path = None
    if apply_openclaw:
        cfg_path = apply_pat_to_openclaw(raw)
    return raw, cfg_path


def restart_openclaw_gateway() -> tuple[bool, str]:
    """Best-effort user systemd restart."""
    if os.environ.get("OPENCLAW_SKIP_GATEWAY_RESTART", "").strip() in ("1", "true", "yes"):
        return False, "skipped (OPENCLAW_SKIP_GATEWAY_RESTART)"
    cmd = ["systemctl", "--user", "restart", "openclaw-gateway.service"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if proc.returncode == 0:
        return True, "restarted openclaw-gateway"
    detail = (proc.stderr or proc.stdout or "").strip()
    return False, detail or f"exit {proc.returncode}"
