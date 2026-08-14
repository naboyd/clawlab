"""Apply approved IOS config changes via netmiko."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Callable

import secrets_store

# Imported lazily from server to avoid circular imports at module load.
_get_host: Callable[[str], dict[str, Any]] | None = None
_platform: Callable[[dict[str, Any]], str] | None = None
_netmiko_type: Callable[[str], str] | None = None
_connect_timeout: int = 10
_command_timeout: int = 30
_expand: Callable[[str | None], str | None] | None = None


def configure(
    *,
    get_host: Callable[[str], dict[str, Any]],
    platform_fn: Callable[[dict[str, Any]], str],
    netmiko_type_fn: Callable[[str], str],
    expand_fn: Callable[[str | None], str | None],
    connect_timeout: int,
    command_timeout: int,
) -> None:
    global _get_host, _platform, _netmiko_type, _expand, _connect_timeout, _command_timeout
    _get_host = get_host
    _platform = platform_fn
    _netmiko_type = netmiko_type_fn
    _expand = expand_fn
    _connect_timeout = connect_timeout
    _command_timeout = command_timeout


def _connect(host_name: str):
    if _get_host is None:
        raise RuntimeError("network_apply.configure() was not called")
    from netmiko import ConnectHandler

    h = _get_host(host_name)
    try:
        login_pw = secrets_store.get_secret(host_name, "login")
        enable_pw = secrets_store.get_secret(host_name, "enable")
    except secrets_store.DecryptionError as exc:
        raise RuntimeError(str(exc)) from exc

    key_path = h.get("key_path")
    if not login_pw and not key_path:
        raise RuntimeError(f"No login credentials for '{host_name}'")

    params: dict[str, Any] = {
        "device_type": _netmiko_type(_platform(h)),
        "host": h["hostname"],
        "port": int(h.get("port", 22)),
        "username": h["username"],
        "conn_timeout": _connect_timeout,
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

    conn = ConnectHandler(**params)
    if params.get("secret"):
        try:
            if not conn.check_enable_mode():
                conn.enable()
        except Exception:
            if not conn.check_enable_mode():
                raise
    return conn


def backup_running_config(host_name: str, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    conn = None
    try:
        conn = _connect(host_name)
        output = conn.send_command("show running-config", read_timeout=_command_timeout)
        path = dest_dir / f"{host_name}-running-config.txt"
        path.write_text(output)
        return path
    finally:
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:
                pass


def run_show(host_name: str, command: str) -> str:
    conn = None
    try:
        conn = _connect(host_name)
        return conn.send_command(command, read_timeout=_command_timeout)
    finally:
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:
                pass


def apply_config_lines(host_name: str, lines: list[str]) -> list[str]:
    conn = None
    try:
        conn = _connect(host_name)
        output = conn.send_config_set(lines, read_timeout=_command_timeout, exit_config_mode=True)
        return [output] if output else []
    finally:
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:
                pass


def write_memory(host_name: str) -> str:
    conn = None
    try:
        conn = _connect(host_name)
        return conn.save_config()
    finally:
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:
                pass


def _check_verify_output(out: str, expect: str) -> bool:
    text = out.strip()
    if "% Invalid" in text:
        return False
    lower = text.lower()
    if expect == "config_present":
        return bool(text)
    if expect == "config_absent":
        return not text
    if expect == "admin_down":
        return "administratively down" in lower
    if expect == "admin_up":
        return "administratively down" not in lower
    return bool(text)


def _command_from_verify_entry(entry: Any) -> str:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        return str(entry.get("command") or "")
    return str(entry)


def _evaluate_structured_verify(out: str, entry: dict[str, Any]) -> tuple[bool, str]:
    text = out.strip()
    if "% Invalid" in text:
        return False, "invalid_input"
    if "expect_contains" in entry:
        val = str(entry["expect_contains"])
        return val in text, f"expect_contains:{val!r}"
    if "expect_not_contains" in entry:
        val = str(entry["expect_not_contains"])
        return val not in text, f"expect_not_contains:{val!r}"
    if entry.get("expect_empty") is True:
        return not text, "expect_empty"
    if entry.get("expect_empty") is False:
        return bool(text), "expect_nonempty"
    if "expect_regex" in entry:
        pat = str(entry["expect_regex"])
        matched = bool(re.search(pat, text, re.MULTILINE))
        return matched, f"expect_regex:{pat!r}"
    if "expect_not_regex" in entry:
        pat = str(entry["expect_not_regex"])
        matched = bool(re.search(pat, text, re.MULTILINE))
        return not matched, f"expect_not_regex:{pat!r}"
    return bool(text), "default_present"


def verify_target(target: dict[str, Any], *, expect_present: bool | None = None) -> tuple[bool, list[dict[str, str]]]:
    host = target["name"]
    results: list[dict[str, str]] = []
    ok = True
    verify_expect = str(target.get("verify_expect") or "config_present")
    for entry in target.get("verify") or []:
        cmd = _command_from_verify_entry(entry)
        out = run_show(host, cmd)
        expectation = verify_expect
        if isinstance(entry, dict) and any(
            key in entry for key in (
                "expect_contains",
                "expect_not_contains",
                "expect_empty",
                "expect_regex",
                "expect_not_regex",
            )
        ):
            passed, expectation = _evaluate_structured_verify(out, entry)
        elif verify_expect:
            passed = _check_verify_output(out, verify_expect)
        else:
            present = bool(out.strip()) and "% Invalid" not in out
            passed = present if expect_present else not present
        row = {
            "command": cmd,
            "passed": str(passed),
            "stdout": out[:2000],
            "expectation": expectation,
        }
        results.append(row)
        if not passed:
            ok = False
    return ok, results
