#!/usr/bin/env python3
"""
Encrypted secrets store for ssh-ops.

Sudo passwords are encrypted with Fernet (AES-128-CBC + HMAC) and stored as
ciphertext in a .env file. The symmetric key lives in a SEPARATE keyfile with
0600 permissions, auto-generated on first use. Decryption requires both files.

Paths (override via env):
  SSH_OPS_HOME     app directory                (default: this file's dir)
  SSH_OPS_KEYFILE  master key file              (default: $HOME/.ssh_ops/master.key)
  SSH_OPS_ENV      encrypted secrets file       (default: <app>/.env)

Keeping the keyfile outside the project dir by default reduces the chance of
committing it. Both keyfile and .env are written 0600.
"""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

APP_DIR = Path(os.environ.get("SSH_OPS_HOME", Path(__file__).parent)).resolve()
KEYFILE = Path(
    os.environ.get("SSH_OPS_KEYFILE", Path.home() / ".ssh_ops" / "master.key")
).expanduser()
ENV_FILE = Path(os.environ.get("SSH_OPS_ENV", APP_DIR / ".env")).expanduser()

PREFIX = "SUDO_PW__"  # legacy/default; env keys look like SUDO_PW__web1=<ciphertext>

# Secret "kinds" and their env-key prefixes.
#   sudo   -> Linux sudo password (sudo -S)
#   login  -> network device login password (e.g. Cisco IOS-XE)
#   enable -> network device enable/privileged-mode password
KIND_PREFIX = {
    "sudo": "SUDO_PW__",
    "login": "LOGIN_PW__",
    "enable": "ENABLE_PW__",
    "sidecar": "DHCP_SIDECAR_TOKEN__",
}


class DecryptionError(RuntimeError):
    """Raised when a secret cannot be decrypted with the current key."""


def _load_or_create_key() -> bytes:
    if KEYFILE.exists():
        return KEYFILE.read_bytes().strip()
    KEYFILE.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    KEYFILE.write_bytes(key)
    os.chmod(KEYFILE, 0o600)
    return key


def _fernet() -> Fernet:
    return Fernet(_load_or_create_key())


def _read_env() -> dict[str, str]:
    data: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip()
    return data


def _write_env(data: dict[str, str]) -> None:
    lines = [
        "# ssh-ops encrypted secrets — DO NOT edit by hand or commit.",
        "# Values are Fernet ciphertext; decryption needs the master keyfile.",
    ]
    for k, v in sorted(data.items()):
        lines.append(f"{k}={v}")
    ENV_FILE.write_text("\n".join(lines) + "\n")
    os.chmod(ENV_FILE, 0o600)


def _kind_prefix(kind: str) -> str:
    try:
        return KIND_PREFIX[kind]
    except KeyError:
        raise ValueError(
            f"Unknown secret kind '{kind}'. Valid: {', '.join(KIND_PREFIX)}"
        )


def set_secret(host: str, kind: str, password: str) -> None:
    """Encrypt and store a secret of `kind` for `host` (sudo|login|enable)."""
    token = _fernet().encrypt(password.encode()).decode()
    data = _read_env()
    data[_kind_prefix(kind) + host] = token
    _write_env(data)


def get_secret(host: str, kind: str) -> str | None:
    """Return the decrypted secret of `kind` for `host`, or None if unset."""
    token = _read_env().get(_kind_prefix(kind) + host)
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise DecryptionError(
            f"Could not decrypt {kind} secret for '{host}'. "
            "Wrong or missing keyfile?"
        ) from exc


def delete_secret(host: str, kind: str) -> None:
    data = _read_env()
    if data.pop(_kind_prefix(kind) + host, None) is not None:
        _write_env(data)


def delete_all_secrets(host: str) -> None:
    """Remove every stored secret (all kinds) for `host`."""
    data = _read_env()
    changed = False
    for prefix in KIND_PREFIX.values():
        if data.pop(prefix + host, None) is not None:
            changed = True
    if changed:
        _write_env(data)


def hosts_with_secret(kind: str = "sudo") -> list[str]:
    """Names of hosts that have a stored secret of `kind`."""
    prefix = _kind_prefix(kind)
    return sorted(k[len(prefix):] for k in _read_env() if k.startswith(prefix))


# ---- Backward-compatible sudo wrappers -----------------------------------

def set_sudo_password(host: str, password: str) -> None:
    set_secret(host, "sudo", password)


def get_sudo_password(host: str) -> str | None:
    return get_secret(host, "sudo")


def delete_sudo_password(host: str) -> None:
    delete_secret(host, "sudo")


# ---- MCP bearer token (HTTP transport auth) ------------------------------
import secrets as _pysecrets

_MCP_CUR = "MCP_TOKEN__current"
_MCP_PREV = "MCP_TOKEN__previous"


def _enc_token(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def _dec_token(cipher: str):
    try:
        return _fernet().decrypt(cipher.encode()).decode()
    except InvalidToken:
        return None


def get_mcp_token():
    v = _read_env().get(_MCP_CUR)
    return _dec_token(v) if v else None


def has_mcp_previous() -> bool:
    return bool(_read_env().get(_MCP_PREV))


def get_mcp_tokens():
    data = _read_env()
    out = []
    for k in (_MCP_CUR, _MCP_PREV):
        v = data.get(k)
        if v:
            p = _dec_token(v)
            if p:
                out.append(p)
    return out


def set_mcp_token(token: str, keep_previous: bool = True) -> None:
    data = _read_env()
    if keep_previous and data.get(_MCP_CUR):
        data[_MCP_PREV] = data[_MCP_CUR]
    data[_MCP_CUR] = _enc_token(token)
    _write_env(data)


def rotate_mcp_token() -> str:
    tok = _pysecrets.token_urlsafe(32)
    set_mcp_token(tok, keep_previous=True)
    return tok


def clear_mcp_previous() -> None:
    data = _read_env()
    if data.pop(_MCP_PREV, None) is not None:
        _write_env(data)


def ensure_mcp_token() -> str:
    t = get_mcp_token()
    return t if t else rotate_mcp_token()


if __name__ == "__main__":  # tiny self-test / CLI
    import sys

    if len(sys.argv) >= 5 and sys.argv[1] == "set" and sys.argv[2] in KIND_PREFIX:
        set_secret(sys.argv[3], sys.argv[2], sys.argv[4])
        print(f"stored {sys.argv[2]} secret for {sys.argv[3]} in {ENV_FILE}")
    elif len(sys.argv) == 4 and sys.argv[1] == "set":
        set_sudo_password(sys.argv[2], sys.argv[3])
        print(f"stored sudo secret for {sys.argv[2]} in {ENV_FILE}")
    elif len(sys.argv) == 4 and sys.argv[1] == "get":
        if sys.argv[2] in KIND_PREFIX:
            print(get_secret(sys.argv[3], sys.argv[2]))
        else:
            print(get_sudo_password(sys.argv[2]))
    elif len(sys.argv) == 3 and sys.argv[1] == "get":
        print(get_sudo_password(sys.argv[2]))
    elif len(sys.argv) == 3 and sys.argv[1] == "del":
        delete_all_secrets(sys.argv[2])
        print("deleted")
    elif len(sys.argv) == 3 and sys.argv[1] == "list":
        kind = sys.argv[2] if len(sys.argv) > 2 else "sudo"
        print("\n".join(hosts_with_secret(kind)) or "(none)")
    else:
        print(
            "usage: secrets_store.py "
            "[set KIND HOST VALUE | set HOST PW | get KIND HOST | get HOST | del HOST | list [KIND]]"
        )
