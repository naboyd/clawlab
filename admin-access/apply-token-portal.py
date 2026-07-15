#!/usr/bin/env python3
# Token auth for OpenClaw behind same-host nginx + claw-auth.
#
# OpenClaw does NOT support trusted-proxy for same-host loopback reverse proxies
# (nginx -> 127.0.0.1:18789). Use token mode + hub #token= fragment instead.
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
TOKEN_ENV = "OPENCLAW_GATEWAY_TOKEN"
TOKEN_REF = TOKEN_ENV


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


def _ensure_gateway_token() -> None:
    env = _read_env_file(ENV_PATH)
    env.update(_read_env_file(SYSTEMD_ENV_PATH))
    if TOKEN_ENV in env and env[TOKEN_ENV] and env[TOKEN_ENV] != "REPLACE_WITH_A_LONG_RANDOM_STRING":
        return

    for bak_name in (".pre-trustedproxy.bak", ".pre-portal-basepath.bak"):
        bak = Path(str(CONFIG_PATH) + bak_name)
        if not bak.is_file():
            continue
        old = json.loads(bak.read_text())
        tok = old.get("gateway", {}).get("auth", {}).get("token")
        if tok and tok not in (TOKEN_REF, TOKEN_ENV) and not str(tok).startswith("OPENCLAW_"):
            _upsert_env_var(ENV_PATH, TOKEN_ENV, str(tok))
            _upsert_env_var(SYSTEMD_ENV_PATH, TOKEN_ENV, str(tok))
            print(f"Restored {TOKEN_ENV} from {bak.name}")
            return

    secret = secrets.token_urlsafe(32)
    _upsert_env_var(ENV_PATH, TOKEN_ENV, secret)
    _upsert_env_var(SYSTEMD_ENV_PATH, TOKEN_ENV, secret)
    print(f"Set {TOKEN_ENV} in {ENV_PATH} and {SYSTEMD_ENV_PATH}")


def main() -> int:
    if not CONFIG_PATH.is_file():
        print(f"Missing {CONFIG_PATH}", file=sys.stderr)
        return 1

    c = json.loads(CONFIG_PATH.read_text())
    gw = c.setdefault("gateway", {})
    auth = gw.setdefault("auth", {})

    _ensure_gateway_token()

    shutil.copy(CONFIG_PATH, str(CONFIG_PATH) + ".pre-token-portal.bak")

    gw["bind"] = "loopback"
    gw.pop("trustedProxies", None)
    auth.pop("trustedProxy", None)
    auth.pop("password", None)
    auth["mode"] = "token"
    auth["token"] = TOKEN_REF

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

    CONFIG_PATH.write_text(json.dumps(c, indent=2) + "\n")
    print("token auth enabled; backup:", str(CONFIG_PATH) + ".pre-token-portal.bak")
    print("mode =", auth.get("mode"), "| token =", auth.get("token"))
    print("trustedProxy removed:", "trustedProxy" not in auth)
    print("controlUi.basePath =", ui["basePath"])
    print("allowedOrigins:", ", ".join(ui["allowedOrigins"]))
    print("Open Control UI from the portal hub button (passes #token= fragment).")
    print("Re-run install-portals.sh to refresh nginx (no auth_request on /openclaw/).")
    print("Restart: systemctl --user restart openclaw-gateway claw-auth")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
