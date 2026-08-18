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

LIB = Path(__file__).resolve().parent / "lib"
sys.path.insert(0, str(LIB))
from openclaw_config import load_openclaw_json, save_openclaw_json  # noqa: E402

OC_HOME = Path(os.environ.get("OPENCLAW_HOME", Path.home() / ".openclaw")).expanduser()
CONFIG_PATH = OC_HOME / "openclaw.json"
ENV_PATH = OC_HOME / ".env"
SYSTEMD_ENV_PATH = OC_HOME / "gateway.systemd.env"
TOKEN_ENV = "OPENCLAW_GATEWAY_TOKEN"
# SecretRef shorthand — plain "OPENCLAW_GATEWAY_TOKEN" is treated as a literal token
# string by the CLI, while the gateway daemon resolves the homonymous env var.
TOKEN_SECRET_REF = f"${{{TOKEN_ENV}}}"


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


def _sync_env_token_files() -> None:
    """Keep ~/.openclaw/.env and gateway.systemd.env on the same token value."""
    env = _read_env_file(ENV_PATH)
    systemd = _read_env_file(SYSTEMD_ENV_PATH)
    token = systemd.get(TOKEN_ENV) or env.get(TOKEN_ENV)
    if not token or token == "REPLACE_WITH_A_LONG_RANDOM_STRING":
        return
    if env.get(TOKEN_ENV) and env.get(TOKEN_ENV) != token:
        print(f"Syncing {ENV_PATH} token to match {SYSTEMD_ENV_PATH.name}")
    _upsert_env_var(ENV_PATH, TOKEN_ENV, token)
    _upsert_env_var(SYSTEMD_ENV_PATH, TOKEN_ENV, token)


def _ensure_gateway_token() -> None:
    _sync_env_token_files()
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
        if tok and tok not in (TOKEN_SECRET_REF, TOKEN_ENV) and not str(tok).startswith(
            ("OPENCLAW_", "${")
        ):
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

    c, _repaired = load_openclaw_json(CONFIG_PATH)
    gw = c.setdefault("gateway", {})
    auth = gw.setdefault("auth", {})

    _ensure_gateway_token()

    shutil.copy(CONFIG_PATH, str(CONFIG_PATH) + ".pre-token-portal.bak")

    gw["bind"] = "loopback"
    gw["mode"] = "local"
    gw.pop("host", None)
    gw["trustedProxies"] = ["127.0.0.1", "::1"]
    auth.pop("trustedProxy", None)
    auth.pop("password", None)
    auth["mode"] = "token"
    auth["token"] = TOKEN_SECRET_REF
    # Local loopback CLI uses gateway.auth.token / OPENCLAW_GATEWAY_TOKEN env.
    # gateway.remote.token in local mode confuses the CLI into sending the env
    # var *name* as the token instead of resolving the env value.
    gw.setdefault("remote", {}).pop("token", None)

    ui = gw.setdefault("controlUi", {})
    domain = os.environ.get("DOMAIN", "lab.example.com")
    port = os.environ.get("PORT_PORTAL", "8443")
    scheme = os.environ.get("SCHEME", "https").strip().lower()
    origins = {
        "http://127.0.0.1:18789",
        "http://localhost:18789",
    }
    if scheme == "http":
        origins.update(
            {
                f"http://{domain}:{port}",
                f"http://127.0.0.1:{port}",
                f"http://localhost:{port}",
            }
        )
    else:
        origins.update(
            {
                f"https://{domain}:{port}",
                f"https://192.168.1.10:{port}",
                f"https://lab-host:{port}",
            }
        )
    ui["allowedOrigins"] = sorted(origins | set(ui.get("allowedOrigins") or []))
    ui["basePath"] = "/openclaw"
    # SSH tunnel / plain HTTP needs token-only auth (no WebCrypto device identity).
    ui["allowInsecureAuth"] = True

    CONFIG_PATH.write_text(json.dumps(c, indent=2) + "\n")
    if _repaired:
        print("Repaired invalid JSON control characters in", CONFIG_PATH)
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
