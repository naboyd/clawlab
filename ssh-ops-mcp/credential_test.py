"""
Test SSH credentials for a configured host (used by MCP Admin).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import paramiko

import secrets_store

NETMIKO_ALIASES = {
    "ios": "cisco_ios",
    "ios-xe": "cisco_ios",
    "iosxe": "cisco_ios",
    "cisco": "cisco_ios",
    "cisco_ios": "cisco_ios",
    "cisco_xe": "cisco_xe",
    "nxos": "cisco_nxos",
    "cisco_nxos": "cisco_nxos",
    "asa": "cisco_asa",
    "cisco_asa": "cisco_asa",
    "arista": "arista_eos",
    "arista_eos": "arista_eos",
    "junos": "juniper_junos",
    "juniper": "juniper_junos",
}

CONNECT_TIMEOUT = int(os.environ.get("SSH_OPS_CONNECT_TIMEOUT", "15"))


@dataclass
class TestResult:
    ok: bool
    message: str


def _expand(path: str | None) -> str | None:
    if not path:
        return path
    return os.path.expanduser(path)


def _platform(host: dict[str, Any]) -> str:
    return str(host.get("platform", "linux") or "linux").strip().lower()


def _is_network(host: dict[str, Any]) -> bool:
    return _platform(host) not in ("linux", "unix", "")


def _netmiko_type(platform: str) -> str:
    return NETMIKO_ALIASES.get(platform, platform)


def _version_snippet(output: str) -> str:
    for line in output.splitlines():
        text = line.strip()
        if text and ("Version" in text or "version" in text or "Cisco" in text):
            return text[:120]
    first = next((ln.strip() for ln in output.splitlines() if ln.strip()), "")
    return first[:120] or "(no output)"


def test_host(
    name: str,
    host: dict[str, Any],
    *,
    login_pw: str | None = None,
    enable_pw: str | None = None,
    cred_source: str = "stored secrets",
) -> TestResult:
    """
    Test credentials against a host.

    Omitted login_pw/enable_pw are loaded from encrypted secrets when available.
    """
    target = f"{name} ({host.get('hostname', '?')})"
    plat = _platform(host)

    try:
        if login_pw is None:
            login_pw = secrets_store.get_secret(name, "login")
        if enable_pw is None:
            enable_pw = secrets_store.get_secret(name, "enable")
    except secrets_store.DecryptionError as exc:
        return TestResult(False, f"✗ {target}: could not decrypt stored secret — {exc}")

    if _is_network(host):
        return _test_network(name, host, target, plat, login_pw, enable_pw, cred_source)
    return _test_linux(name, host, target, login_pw, cred_source)


def _test_network(
    name: str,
    host: dict[str, Any],
    target: str,
    plat: str,
    login_pw: str | None,
    enable_pw: str | None,
    cred_source: str,
) -> TestResult:
    try:
        from netmiko import ConnectHandler
    except ImportError:
        return TestResult(False, f"✗ {target}: netmiko is not installed")

    key_path = host.get("key_path")
    if not login_pw and not key_path:
        return TestResult(
            False,
            f"✗ {target}: no login password provided and no stored login secret / key_path",
        )

    params: dict[str, Any] = {
        "device_type": _netmiko_type(plat),
        "host": host["hostname"],
        "port": int(host.get("port", 22)),
        "username": host.get("username", ""),
        "conn_timeout": CONNECT_TIMEOUT,
        "fast_cli": False,
        "use_keys": False,
        "allow_agent": False,
    }

    if login_pw:
        params["password"] = login_pw
        params["secret"] = enable_pw or login_pw
    elif key_path:
        params["use_keys"] = True
        params["key_file"] = _expand(key_path)
        if enable_pw:
            params["secret"] = enable_pw

    conn = None
    try:
        conn = ConnectHandler(**params)
        if params.get("secret"):
            try:
                if not conn.check_enable_mode():
                    conn.enable()
            except Exception:
                if not conn.check_enable_mode():
                    raise
        out = conn.send_command("show version", read_timeout=CONNECT_TIMEOUT)
        snippet = _version_snippet(out)
        return TestResult(True, f"✓ {target}: connected ({cred_source}) — {snippet}")
    except Exception as exc:
        return TestResult(False, f"✗ {target}: {type(exc).__name__}: {exc}")
    finally:
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:
                pass


def _test_linux(
    name: str,
    host: dict[str, Any],
    target: str,
    login_pw: str | None,
    cred_source: str,
) -> TestResult:
    client = None
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        connect_kwargs: dict[str, Any] = {
            "hostname": host["hostname"],
            "port": int(host.get("port", 22)),
            "username": host.get("username", ""),
            "timeout": CONNECT_TIMEOUT,
            "allow_agent": host.get("allow_agent", True),
            "look_for_keys": host.get("look_for_keys", True),
        }
        if login_pw:
            connect_kwargs["password"] = login_pw
            connect_kwargs["allow_agent"] = False
            connect_kwargs["look_for_keys"] = False
        elif host.get("key_path"):
            connect_kwargs["key_filename"] = _expand(host["key_path"])
        else:
            return TestResult(
                False,
                f"✗ {target}: no login password provided and no stored login secret / key_path",
            )

        client.connect(**connect_kwargs)
        _, stdout, stderr = client.exec_command("uname -n", timeout=CONNECT_TIMEOUT)
        out = stdout.read().decode("utf-8", "replace").strip()
        err = stderr.read().decode("utf-8", "replace").strip()
        if not out and err:
            return TestResult(False, f"✗ {target}: connected but command failed — {err[:120]}")
        return TestResult(True, f"✓ {target}: connected ({cred_source}) — hostname {out or '(unknown)'}")
    except Exception as exc:
        return TestResult(False, f"✗ {target}: {type(exc).__name__}: {exc}")
    finally:
        if client:
            client.close()
