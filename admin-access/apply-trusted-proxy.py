#!/usr/bin/env python3
# Enable trusted-proxy auth in ~/.openclaw/openclaw.json for claw-auth + nginx.
# Preserves gateway.auth.password via OPENCLAW_GATEWAY_PASSWORD env reference.
import json
import os
import secrets
import shutil
import sys
from pathlib import Path

OC_HOME = Path(os.environ.get("OPENCLAW_HOME", Path.home() / ".openclaw")).expanduser()
CONFIG_PATH = OC_HOME / "openclaw.json"
ENV_PATH = OC_HOME / ".env"
SYSTEMD_ENV_PATH = OC_HOME / "gateway.systemd.env"
PASSWORD_ENV = "OPENCLAW_GATEWAY_PASSWORD"
PASSWORD_REF = PASSWORD_ENV  # openclaw.json references env var by name
TOKEN_ENV = "OPENCLAW_GATEWAY_TOKEN"


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def _upsert_env_var(path: Path, key: str, value: str) -> None:
    lines: list[str] = []
    found = False
    if path.is_file():
        for line in path.read_text().splitlines():
            if line.startswith(f"{key}="):
                lines.append(f"{key}={value}")
                found = True
            else:
                lines.append(line)
    if not found:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"{key}={value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _remove_env_var(path: Path, key: str) -> bool:
    if not path.is_file():
        return False
    kept: list[str] = []
    removed = False
    for line in path.read_text().splitlines():
        if line.startswith(f"{key}="):
            removed = True
            continue
        kept.append(line)
    if removed:
        path.write_text("\n".join(kept).rstrip() + ("\n" if kept else ""))
    return removed


def _ensure_gateway_password() -> None:
    env = _read_env_file(ENV_PATH)
    env.update(_read_env_file(SYSTEMD_ENV_PATH))
    if PASSWORD_ENV in env and env[PASSWORD_ENV] and env[PASSWORD_ENV] != "REPLACE_WITH_A_LONG_RANDOM_STRING":
        return
    secret = secrets.token_urlsafe(32)
    _upsert_env_var(ENV_PATH, PASSWORD_ENV, secret)
    _upsert_env_var(SYSTEMD_ENV_PATH, PASSWORD_ENV, secret)
    print(f"Set {PASSWORD_ENV} in {ENV_PATH} and {SYSTEMD_ENV_PATH}")


def main() -> int:
    if not CONFIG_PATH.is_file():
        print(f"Missing {CONFIG_PATH}", file=sys.stderr)
        return 1

    c = json.loads(CONFIG_PATH.read_text())
    gw = c.setdefault("gateway", {})
    auth = gw.setdefault("auth", {})

    _ensure_gateway_password()

    shutil.copy(CONFIG_PATH, str(CONFIG_PATH) + ".pre-trustedproxy.bak")

    gw["bind"] = "loopback"
    gw["trustedProxies"] = ["127.0.0.1", "::1"]
    auth["mode"] = "trusted-proxy"
    auth["password"] = PASSWORD_REF
    auth.pop("token", None)
    auth["trustedProxy"] = {
        "userHeader": "x-forwarded-user",
        # Do not set requiredHeaders: loopback gateway-client backends connect
        # directly without proxy headers; requiredHeaders makes OpenClaw reject
        # them before password fallback (trusted_proxy_missing_header_*).
        "allowUsers": [],
        "allowLoopback": True,
    }
    ui = gw.setdefault("controlUi", {})
    domain = os.environ.get("DOMAIN", "icecream.naboydciscolab.com")
    port = os.environ.get("PORT_PORTAL", "8443")
    origins = {
        f"https://{domain}:{port}",
        f"https://192.168.128.93:{port}",
        f"https://icecream:{port}",
    }
    ui["allowedOrigins"] = sorted(origins | set(ui.get("allowedOrigins") or []))
    ui["basePath"] = "/openclaw"

    removed_token = _remove_env_var(ENV_PATH, TOKEN_ENV)
    removed_token |= _remove_env_var(SYSTEMD_ENV_PATH, TOKEN_ENV)

    CONFIG_PATH.write_text(json.dumps(c, indent=2) + "\n")
    print("trusted-proxy enabled; backup:", str(CONFIG_PATH) + ".pre-trustedproxy.bak")
    print("mode =", auth["mode"], "| password =", PASSWORD_REF)
    if removed_token:
        print(f"removed {TOKEN_ENV} from env files (mutually exclusive with trusted-proxy)")
    print("controlUi.basePath =", ui["basePath"])
    print("Restart: systemctl --user restart openclaw-gateway")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
