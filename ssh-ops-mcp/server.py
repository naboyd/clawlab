#!/usr/bin/env python3
"""
ssh-ops MCP server
==================

An MCP (Model Context Protocol) server that exposes safe, allowlisted SSH
operations across a fixed inventory of Linux hosts. Designed for log digging
and crash diagnosis, with an opt-in ability to restart specific named services.

Security model (read this):
  * The server runs on YOUR machine/infra. Your SSH keys and host inventory
    never leave it. The MCP client only ever sees tool *results*.
  * `run_command` accepts ONLY read-only commands whose first token (per pipe
    segment) is on READ_ONLY_BINARIES. Shell metacharacters that enable
    chaining/redirection (; && || ` $() > < & newlines) are rejected.
  * `restart_service` only works for services explicitly allowlisted per host
    in the config (`allowed_services`). Nothing else can be mutated.
  * Every tool call is appended to an audit log with host + timestamp.

Run:
    pip install -r requirements.txt
    export SSH_OPS_CONFIG=/path/to/hosts.yaml
    python server.py
"""

from __future__ import annotations

import os
import re
import shlex
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import paramiko
import yaml
from mcp.server.fastmcp import FastMCP

import inventory
import secrets_store
import change_engine
import change_actor
import network_apply

# --------------------------------------------------------------------------- #
# Configuration loading
# --------------------------------------------------------------------------- #

CONFIG_PATH = os.environ.get("SSH_OPS_CONFIG", "hosts.yaml")


def _expand(p: str | None) -> str | None:
    return str(Path(os.path.expanduser(p)).resolve()) if p else None


def load_config(path: str = CONFIG_PATH) -> dict[str, Any]:
    cfg_file = Path(os.path.expanduser(path))
    if not cfg_file.exists():
        raise FileNotFoundError(
            f"Config not found at {cfg_file}. Set SSH_OPS_CONFIG or create hosts.yaml."
        )
    with cfg_file.open() as fh:
        cfg = yaml.safe_load(fh) or {}
    cfg.setdefault("settings", {})
    cfg.setdefault("hosts", {})
    if not cfg["hosts"]:
        raise ValueError("Config has no hosts defined.")
    return cfg


CONFIG = load_config()
SETTINGS = CONFIG["settings"]
HOSTS: dict[str, dict[str, Any]] = CONFIG["hosts"]

# Hot-reload: re-read hosts.yaml when it changes on disk, so hosts added via
# the GUI (or an external agent) are picked up without restarting the server.
_HOSTS_CACHE: dict[str, Any] = {"mtime": None, "hosts": HOSTS}


def _current_hosts() -> dict[str, dict[str, Any]]:
    path = os.path.expanduser(CONFIG_PATH)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return _HOSTS_CACHE["hosts"]
    if _HOSTS_CACHE["mtime"] != mtime:
        try:
            _HOSTS_CACHE["hosts"] = load_config()["hosts"]
            _HOSTS_CACHE["mtime"] = mtime
        except Exception:  # noqa: BLE001 - keep serving the last good config
            pass
    return _HOSTS_CACHE["hosts"]


COMMAND_TIMEOUT = int(SETTINGS.get("command_timeout", 30))
CONNECT_TIMEOUT = int(SETTINGS.get("connect_timeout", 10))
AUDIT_LOG = _expand(SETTINGS.get("audit_log", "./ssh_ops_audit.log"))

# File-transfer sandbox: the container-side folder that upload/download are
# confined to. Mount it so files are visible on the host. Remote side may be
# any path. Downloads land here; uploads are read from here.
_default_transfers = "/data/transfers" if Path("/data").is_dir() else "./transfers"
TRANSFERS_DIR = Path(_expand(SETTINGS.get("transfers_dir", _default_transfers)))
MAX_TRANSFER_BYTES = int(SETTINGS.get("max_transfer_mb", 200)) * 1024 * 1024
try:
    TRANSFERS_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass

# --------------------------------------------------------------------------- #
# Audit logging
# --------------------------------------------------------------------------- #

logging.basicConfig(level=logging.INFO, format="%(message)s")
audit = logging.getLogger("ssh_ops.audit")
audit.propagate = False
if AUDIT_LOG:
    _h = logging.FileHandler(AUDIT_LOG)
    _h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    audit.addHandler(_h)
# Also echo to stderr so it shows up in the MCP client's server logs.
_s = logging.StreamHandler()
_s.setFormatter(logging.Formatter("[audit] %(message)s"))
audit.addHandler(_s)
audit.setLevel(logging.INFO)


def _audit(host: str, action: str, detail: str) -> None:
    audit.info("host=%s action=%s detail=%s", host, action, detail)


# --------------------------------------------------------------------------- #
# Command safety
# --------------------------------------------------------------------------- #

# First-token binaries permitted in run_command. All strictly read-only.
READ_ONLY_BINARIES = {
    "journalctl", "dmesg", "cat", "tail", "head", "grep", "egrep", "zgrep",
    "less", "wc", "df", "du", "free", "uptime", "who", "w", "last", "lastb",
    "ps", "pgrep", "ss", "netstat", "vmstat", "iostat", "mpstat", "sar",
    "uname", "hostname", "hostnamectl", "date", "ls", "stat", "find", "awk",
    "sed", "sort", "uniq", "cut", "lsof", "lscpu", "lsblk", "ip", "id",
    "env", "printenv", "top", "loginctl", "timedatectl",
}

# systemctl is allowed only for these (read-only) subcommands via run_command.
SYSTEMCTL_RO_SUBCMDS = {
    "status", "is-active", "is-enabled", "is-failed", "show",
    "list-units", "list-unit-files", "list-timers", "cat",
}

# Patterns that indicate command chaining / redirection / substitution.
DANGEROUS = re.compile(r"[;&`\n\r]|\$\(|\|\||&&|>>|>|<")


# --------------------------------------------------------------------------- #
# Platform handling (Linux vs network devices like Cisco IOS-XE)
# --------------------------------------------------------------------------- #

# Friendly platform aliases -> netmiko device_type.
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

# First-token commands permitted on network devices. All read-only / diagnostic.
NETWORK_READONLY = {
    "show", "dir", "ping", "traceroute", "more", "display", "get", "monitor",
}


def _platform(h: dict[str, Any]) -> str:
    return str(h.get("platform", "linux") or "linux").strip().lower()


def _is_network(h: dict[str, Any]) -> bool:
    """True if the host is a network device (anything but linux/unix)."""
    return _platform(h) not in ("linux", "unix", "")


def _netmiko_type(platform: str) -> str:
    return NETMIKO_ALIASES.get(platform, platform)


class CommandRejected(ValueError):
    """Raised when a command fails the allowlist policy."""


def validate_readonly(command: str) -> None:
    """Raise CommandRejected unless `command` is a safe read-only command.

    Pipes ( | ) are permitted; each segment's first token must be allowlisted.
    All other shell metacharacters are rejected.
    """
    if not command or not command.strip():
        raise CommandRejected("Empty command.")

    # Allow a single pipe operator but nothing else dangerous. We temporarily
    # split on single pipes, then check each segment for other metacharacters.
    segments = re.split(r"(?<!\|)\|(?!\|)", command)  # split on lone '|'
    for seg in segments:
        seg = seg.strip()
        if not seg:
            raise CommandRejected("Empty pipe segment.")
        if DANGEROUS.search(seg):
            raise CommandRejected(
                "Command contains disallowed shell metacharacters "
                "(chaining/redirection/substitution are not permitted)."
            )
        try:
            tokens = shlex.split(seg)
        except ValueError as exc:
            raise CommandRejected(f"Could not parse command: {exc}")
        if not tokens:
            raise CommandRejected("Empty pipe segment.")
        binary = os.path.basename(tokens[0])
        if binary == "systemctl":
            sub = next((t for t in tokens[1:] if not t.startswith("-")), None)
            if sub not in SYSTEMCTL_RO_SUBCMDS:
                raise CommandRejected(
                    f"systemctl '{sub}' is not a read-only subcommand. "
                    "Use restart_service for restarts."
                )
        elif binary not in READ_ONLY_BINARIES:
            raise CommandRejected(
                f"'{binary}' is not on the read-only allowlist."
            )


# Network devices run one CLI line per call (no shell). Reject only newlines,
# which could smuggle a second command; pipes (| include/section) are fine.
NETWORK_DANGEROUS = re.compile(r"[\n\r]")


def validate_network_command(command: str) -> None:
    """Raise CommandRejected unless `command` is a read-only network command.

    The first token must be on NETWORK_READONLY (show, dir, ping, ...). IOS-style
    filters like `show run | include foo` are allowed.
    """
    if not command or not command.strip():
        raise CommandRejected("Empty command.")
    if NETWORK_DANGEROUS.search(command):
        raise CommandRejected("Newlines are not allowed (one command per call).")
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        raise CommandRejected(f"Could not parse command: {exc}")
    if not tokens:
        raise CommandRejected("Empty command.")
    first = tokens[0].lower()
    if first not in NETWORK_READONLY:
        raise CommandRejected(
            f"'{tokens[0]}' is not an allowed read-only command on network "
            f"devices. Allowed first words: {sorted(NETWORK_READONLY)}"
        )


# --------------------------------------------------------------------------- #
# SSH execution
# --------------------------------------------------------------------------- #


def _get_host(name: str) -> dict[str, Any]:
    hosts = _current_hosts()
    if name not in hosts:
        raise ValueError(
            f"Unknown host '{name}'. Known hosts: {', '.join(sorted(hosts))}"
        )
    return hosts[name]


def _connect(name: str) -> paramiko.SSHClient:
    h = _get_host(name)
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    # RejectPolicy is safest; switch to WarningPolicy only if you accept TOFU.
    policy = h.get("host_key_policy", SETTINGS.get("host_key_policy", "reject"))
    if policy == "auto":
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    elif policy == "warn":
        client.set_missing_host_key_policy(paramiko.WarningPolicy())
    else:
        client.set_missing_host_key_policy(paramiko.RejectPolicy())

    connect_kwargs: dict[str, Any] = {
        "hostname": h["hostname"],
        "port": int(h.get("port", 22)),
        "username": h["username"],
        "timeout": CONNECT_TIMEOUT,
        "allow_agent": h.get("allow_agent", True),
        "look_for_keys": h.get("look_for_keys", True),
    }
    # An encrypted SSH login password (secret kind "login") takes precedence and
    # forces password auth — so we don't trip over passphrase-protected keys.
    login_pw = None
    try:
        login_pw = secrets_store.get_secret(name, "login")
    except secrets_store.DecryptionError:
        login_pw = None

    if login_pw:
        connect_kwargs["password"] = login_pw
        connect_kwargs["look_for_keys"] = False
        connect_kwargs["allow_agent"] = False
    else:
        if h.get("key_path"):
            connect_kwargs["key_filename"] = _expand(h["key_path"])
        if h.get("passphrase"):
            connect_kwargs["passphrase"] = h["passphrase"]
        if h.get("password"):
            connect_kwargs["password"] = h["password"]

    client.connect(**connect_kwargs)
    return client


def _run(
    name: str,
    command: str,
    timeout: int | None = None,
    stdin_data: str | None = None,
    get_pty: bool = False,
) -> dict[str, Any]:
    """Execute a raw command over SSH. Internal: callers must pre-validate.

    If `stdin_data` is given it is written to the process's stdin (used to feed
    a sudo password to `sudo -S`). `get_pty` requests a pseudo-terminal, needed
    on hosts with `Defaults requiretty` in sudoers.
    """
    timeout = timeout or COMMAND_TIMEOUT
    client = None
    try:
        client = _connect(name)
        stdin, stdout, stderr = client.exec_command(
            command, timeout=timeout, get_pty=get_pty
        )
        if stdin_data is not None:
            try:
                stdin.write(stdin_data)
                stdin.flush()
                stdin.channel.shutdown_write()
            except Exception:  # noqa: BLE001 - stdin may already be closed
                pass
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        code = stdout.channel.recv_exit_status()
        return {
            "host": name,
            "command": command,
            "exit_code": code,
            "stdout": out,
            "stderr": err,
        }
    except Exception as exc:  # noqa: BLE001 - surface any SSH error to the model
        return {
            "host": name,
            "command": command,
            "exit_code": None,
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {exc}",
        }
    finally:
        if client:
            client.close()


def _run_network(name: str, command: str) -> dict[str, Any]:
    """Run a single read-only CLI command on a network device via netmiko.

    Handles login-password auth, `enable` (privileged mode), and paging.
    Internal: callers must pre-validate with validate_network_command().
    """
    h = _get_host(name)
    try:
        from netmiko import ConnectHandler
    except ImportError:
        return {
            "host": name,
            "command": command,
            "exit_code": None,
            "stdout": "",
            "stderr": "netmiko is not installed. Add it (pip install netmiko) to "
            "use non-Linux platforms.",
        }

    try:
        login_pw = secrets_store.get_secret(name, "login")
        enable_pw = secrets_store.get_secret(name, "enable")
    except secrets_store.DecryptionError as exc:
        return {"host": name, "command": command, "exit_code": None,
                "stdout": "", "stderr": str(exc)}

    key_path = h.get("key_path")
    if not login_pw and not key_path:
        return {
            "host": name,
            "command": command,
            "exit_code": None,
            "stdout": "",
            "stderr": (
                f"No login credentials for '{name}'. Set an encrypted login password "
                "in MCP Admin (Hosts tab → edit host), or configure key_path. "
                "Discovery import only stores secrets for selected devices at import time."
            ),
        }

    params: dict[str, Any] = {
        "device_type": _netmiko_type(_platform(h)),
        "host": h["hostname"],
        "port": int(h.get("port", 22)),
        "username": h["username"],
        "conn_timeout": CONNECT_TIMEOUT,
        "fast_cli": False,
        "use_keys": False,
        "allow_agent": False,
    }

    if login_pw:
        # Password auth — do not fall through to container ~/.ssh keys (common misconfig).
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
        out = conn.send_command(command, read_timeout=COMMAND_TIMEOUT)
        return {
            "host": name,
            "command": command,
            "exit_code": 0,
            "stdout": out,
            "stderr": "",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "host": name,
            "command": command,
            "exit_code": None,
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {exc}",
        }
    finally:
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:  # noqa: BLE001
                pass


# --------------------------------------------------------------------------- #
# MCP tools
# --------------------------------------------------------------------------- #

mcp = FastMCP(
    "ssh-ops",
    host=os.environ.get("SSH_OPS_MCP_HOST", "0.0.0.0"),
    port=int(os.environ.get("SSH_OPS_MCP_PORT", "8766")),
)

_LINUX_ONLY_MSG = (
    "This tool is Linux-only. '{host}' is a {platform} device — use "
    "run_command with a 'show' command instead."
)


def _reject_if_network(host: str) -> dict[str, Any] | None:
    h = _get_host(host)
    if _is_network(h):
        return {
            "host": host,
            "error": _LINUX_ONLY_MSG.format(host=host, platform=_platform(h)),
        }
    return None


@mcp.tool()
def list_hosts() -> list[dict[str, Any]]:
    """List the configured hosts and which services each may restart.

    Returns non-sensitive metadata only (never keys or passwords). Each entry
    includes ``tags`` (list), ``allow_write``, and ``auto_update`` for fleet
    and other tag-driven flows.
    """
    result = []
    login_set = set(secrets_store.hosts_with_secret("login"))
    enable_set = set(secrets_store.hosts_with_secret("enable"))
    for name, h in _current_hosts().items():
        tags = inventory.normalize_tags(h)
        is_net = _is_network(h)
        result.append(
            {
                "name": name,
                "platform": _platform(h),
                "kind": "network" if is_net else "linux",
                "hostname": h.get("hostname"),
                "username": h.get("username"),
                "port": int(h.get("port", 22)),
                "allowed_services": list(h.get("allowed_services", [])),
                "tags": tags,
                "allow_write": bool(h.get("allow_write", False)),
                "auto_update": bool(h.get("auto_update", False))
                or inventory.has_tag(h, "auto_update"),
                "has_login_secret": name in login_set,
                "has_enable_secret": name in enable_set,
                "auth_ready": (
                    (name in login_set or bool(h.get("key_path")))
                    if is_net
                    else True
                ),
            }
        )
    return result


@mcp.tool()
def run_command(host: str, command: str) -> dict[str, Any]:
    """Run a READ-ONLY diagnostic command on `host`.

    Only allowlisted, non-mutating commands are permitted (logs, dmesg, df,
    free, ps, ss, systemctl status, etc.). Pipes to tools like grep are
    allowed; command chaining, redirection, and substitution are rejected.

    On Linux hosts only allowlisted shell commands run. On network devices
    (platform: cisco_ios, etc.) only read-only CLI commands run (show, dir,
    ping, traceroute), executed via netmiko with enable mode + paging handled.

    Args:
        host: A host name from list_hosts().
        command: For Linux, e.g. "journalctl -p err -n 200"; for network gear,
            e.g. "show version" or "show run | include ntp".
    """
    h = _get_host(host)
    if _is_network(h):
        try:
            validate_network_command(command)
        except CommandRejected as exc:
            _audit(host, "run_command.REJECTED", command)
            return {"host": host, "command": command, "error": str(exc)}
        _audit(host, "run_command.net", command)
        return _run_network(host, command)

    try:
        validate_readonly(command)
    except CommandRejected as exc:
        _audit(host, "run_command.REJECTED", command)
        return {"host": host, "command": command, "error": str(exc)}
    _audit(host, "run_command", command)
    return _run(host, command)


@mcp.tool()
def tail_log(host: str, path: str, lines: int = 200) -> dict[str, Any]:
    """Tail the last `lines` of a log file at `path` on `host`.

    Args:
        host: A host name from list_hosts().
        path: Absolute path to a log file, e.g. "/var/log/syslog".
        lines: Number of trailing lines (1-5000).
    """
    if (rej := _reject_if_network(host)) is not None:
        return rej
    lines = max(1, min(int(lines), 5000))
    if not path.startswith("/") or DANGEROUS.search(path):
        return {"host": host, "error": "Path must be an absolute, plain file path."}
    cmd = f"tail -n {lines} {shlex.quote(path)}"
    _audit(host, "tail_log", cmd)
    return _run(host, cmd)


@mcp.tool()
def get_journal(
    host: str,
    unit: str | None = None,
    since: str | None = None,
    priority: str | None = None,
    boot: str | None = None,
    lines: int = 300,
) -> dict[str, Any]:
    """Query systemd journal logs on `host`.

    Args:
        host: A host name from list_hosts().
        unit: Optional service unit, e.g. "nginx".
        since: Optional time filter, e.g. "1 hour ago" or "2026-06-30 08:00".
        priority: Optional max priority, e.g. "err", "warning".
        boot: Optional boot id; use "-1" for the previous boot (great for
              catching what happened right before an unexpected reboot).
        lines: Max lines to return (1-5000).
    """
    if (rej := _reject_if_network(host)) is not None:
        return rej
    lines = max(1, min(int(lines), 5000))
    parts = ["journalctl", "--no-pager", "-n", str(lines)]
    if unit:
        parts += ["-u", shlex.quote(unit)]
    if since:
        parts += ["--since", shlex.quote(since)]
    if priority:
        parts += ["-p", shlex.quote(priority)]
    if boot:
        parts += ["-b", shlex.quote(str(boot))]
    cmd = " ".join(parts)
    _audit(host, "get_journal", cmd)
    return _run(host, cmd)


@mcp.tool()
def check_health(host: str) -> dict[str, Any]:
    """Run a bundle of read-only health checks on `host`.

    Collects uptime, memory, disk usage, recent reboots, failed services,
    and any OOM-killer activity — the usual first-pass crash diagnostics.
    """
    if (rej := _reject_if_network(host)) is not None:
        return rej
    checks = {
        "uptime": "uptime",
        "memory": "free -m",
        "disk": "df -h",
        "load_top": "ps -eo pid,ppid,%cpu,%mem,comm --sort=-%cpu | head -n 12",
        "reboots": "last -x -n 15 reboot shutdown",
        "failed_units": "systemctl --failed --no-pager",
        "oom_killer": "dmesg -T --level=err,warn | grep -i -E 'oom|killed process' | tail -n 30",
    }
    _audit(host, "check_health", "bundle")
    results: dict[str, Any] = {"host": host, "checks": {}}
    for label, cmd in checks.items():
        # These are constructed internally from the allowlist, so they're safe.
        results["checks"][label] = _run(host, cmd)
    return results


@mcp.tool()
def restart_service(host: str, service: str) -> dict[str, Any]:
    """Restart an allowlisted systemd service on `host`.

    The service MUST appear in that host's `allowed_services` config, or the
    request is rejected. Uses `systemctl restart` and returns the post-restart
    status. This is the ONLY mutating operation this server can perform.

    Args:
        host: A host name from list_hosts().
        service: The systemd unit name, e.g. "nginx".
    """
    if (rej := _reject_if_network(host)) is not None:
        return {"host": host, "service": service, "error": rej["error"]}
    h = _get_host(host)
    allowed = set(h.get("allowed_services", []))
    if service not in allowed:
        _audit(host, "restart_service.REJECTED", service)
        return {
            "host": host,
            "service": service,
            "error": f"'{service}' is not in allowed_services for {host}. "
            f"Allowed: {sorted(allowed) or 'none'}",
        }
    svc = shlex.quote(service)
    use_sudo = h.get("use_sudo_for_restart", True)
    get_pty = bool(h.get("use_pty", False))
    stdin_data: str | None = None
    password: str | None = None

    if use_sudo:
        try:
            password = secrets_store.get_sudo_password(host)
        except secrets_store.DecryptionError as exc:
            _audit(host, "restart_service.ERROR", "decrypt_failed")
            return {"host": host, "service": service, "error": str(exc)}
        if password:
            # Feed the password to sudo via stdin; -p '' silences the prompt.
            prefix = "sudo -S -p '' "
            stdin_data = password + "\n"
        else:
            # No stored password: fall back to passwordless sudo.
            prefix = "sudo -n "
    else:
        prefix = ""

    cmd = f"{prefix}systemctl restart {svc} && systemctl status {svc} --no-pager -n 20"
    _audit(host, "restart_service", service)
    result = _run(host, cmd, stdin_data=stdin_data, get_pty=get_pty)

    # Never let the password leak back through echoed output (possible with PTY).
    if password:
        for field in ("stdout", "stderr"):
            if result.get(field):
                result[field] = result[field].replace(password, "***")
        result["command"] = f"{('sudo -S ' if use_sudo else '')}systemctl restart {svc} && systemctl status ..."
    return result


# --------------------------------------------------------------------------- #
# Write command + file transfer (opt-in per host, sandboxed, audited)
# --------------------------------------------------------------------------- #

def _write_allowed(h: dict[str, Any]) -> bool:
    return bool(h.get("allow_write", False))


def _safe_local(name: str) -> Path:
    """Resolve a transfers-relative filename, rejecting path traversal."""
    p = (TRANSFERS_DIR / name).resolve()
    if TRANSFERS_DIR.resolve() not in p.parents and p != TRANSFERS_DIR.resolve():
        raise ValueError(
            f"'{name}' escapes the transfers directory. Use a plain filename."
        )
    return p


def _sftp(name: str):
    """Open an SFTP session on a fresh SSH connection to a Linux host."""
    client = _connect(name)
    return client, client.open_sftp()


@mcp.tool()
def run_write_command(host: str, command: str) -> dict[str, Any]:
    """Run an ARBITRARY (mutating) shell command on a Linux `host`.

    Disabled unless that host has `allow_write: true` in its config — read-only
    is the default everywhere else. There is NO allowlist here, so it can modify
    or delete data; every call is audit-logged. Network devices are not allowed
    (use the network agent for device config).

    Args:
        host: A host name from list_hosts() with allow_write enabled.
        command: The shell command to run.
    """
    h = _get_host(host)
    if _is_network(h):
        return {"host": host, "error": "run_write_command is Linux-only; use the "
                "network agent for device configuration."}
    if not _write_allowed(h):
        return {"host": host, "error": f"Writes are disabled for '{host}'. Set "
                "allow_write: true on this host to enable."}
    if not command or not command.strip():
        return {"host": host, "error": "Empty command."}
    _audit(host, "run_write_command", command)
    return _run(host, command)


@mcp.tool()
def upload_file(host: str, local_name: str, remote_path: str) -> dict[str, Any]:
    """Upload a file from the transfers folder to `remote_path` on `host`.

    Requires `allow_write: true` on the host (it writes to the remote). The
    source must be a plain filename inside the sandboxed transfers directory.

    Args:
        host: A Linux host with allow_write enabled.
        local_name: Filename within the transfers dir (no path separators).
        remote_path: Absolute destination path on the host.
    """
    h = _get_host(host)
    if _is_network(h):
        return {"host": host, "error": "File transfer is Linux-only."}
    if not _write_allowed(h):
        return {"host": host, "error": f"Writes are disabled for '{host}'. Set "
                "allow_write: true to enable uploads."}
    try:
        src = _safe_local(local_name)
    except ValueError as exc:
        return {"host": host, "error": str(exc)}
    if not src.exists():
        return {"host": host, "error": f"'{local_name}' not found in transfers dir."}
    size = src.stat().st_size
    if size > MAX_TRANSFER_BYTES:
        return {"host": host, "error": f"File {size} bytes exceeds max "
                f"{MAX_TRANSFER_BYTES} bytes."}
    _audit(host, "upload_file", f"{local_name} -> {remote_path} ({size}B)")
    client = None
    try:
        client, sftp = _sftp(host)
        sftp.put(str(src), remote_path)
        sftp.close()
        return {"host": host, "uploaded": remote_path, "bytes": size}
    except Exception as exc:  # noqa: BLE001
        return {"host": host, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        if client:
            client.close()


@mcp.tool()
def download_file(host: str, remote_path: str, local_name: str) -> dict[str, Any]:
    """Download `remote_path` from `host` into the transfers folder.

    Reading a remote file is allowed on any Linux host (no allow_write needed);
    the download lands as `local_name` inside the sandboxed transfers directory,
    which is mounted so you can see it on the host. Size-limited and audited.

    Args:
        host: A Linux host.
        remote_path: Absolute path of the file to fetch.
        local_name: Destination filename within the transfers dir.
    """
    h = _get_host(host)
    if _is_network(h):
        return {"host": host, "error": "File transfer is Linux-only."}
    try:
        dst = _safe_local(local_name)
    except ValueError as exc:
        return {"host": host, "error": str(exc)}
    _audit(host, "download_file", f"{remote_path} -> {local_name}")
    client = None
    try:
        client, sftp = _sftp(host)
        try:
            attr = sftp.stat(remote_path)
            if attr.st_size and attr.st_size > MAX_TRANSFER_BYTES:
                sftp.close()
                return {"host": host, "error": f"Remote file {attr.st_size} bytes "
                        f"exceeds max {MAX_TRANSFER_BYTES} bytes."}
        except IOError:
            sftp.close()
            return {"host": host, "error": f"'{remote_path}' not found on {host}."}
        sftp.get(remote_path, str(dst))
        sftp.close()
        return {"host": host, "downloaded": str(dst), "bytes": dst.stat().st_size}
    except Exception as exc:  # noqa: BLE001
        return {"host": host, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        if client:
            client.close()


# --------------------------------------------------------------------------- #
# Approval-gated network changes (propose → human approve → apply)
# --------------------------------------------------------------------------- #

network_apply.configure(
    get_host=_get_host,
    platform_fn=_platform,
    netmiko_type_fn=_netmiko_type,
    expand_fn=_expand,
    connect_timeout=CONNECT_TIMEOUT,
    command_timeout=COMMAND_TIMEOUT,
)


@mcp.tool()
def propose_change(
    host: str,
    change_type: str,
    spec: dict[str, Any],
    intent: str = "",
    requested_by: str = "",
) -> dict[str, Any]:
    """Propose a gated network configuration change (no device writes).

    Creates a change record in ``proposed`` status. A human must approve it in
    MCP Admin before ``apply_change`` will run. Supported change_type values:

    * ``ios_local_user`` — spec: username, password/secret, privilege, action
      (create|delete)
    * ``ios_config_lines`` — spec: lines (list), optional group, optional rollback/verify

    Arbitrary config outside allow_groups in ios-xe-policy.yaml is rejected.

    Args:
        host: Network host name from list_hosts().
        change_type: e.g. ``ios_local_user``, ``ios_interface_state``, ``ios_config_lines``.
        spec: Structured change parameters (see change_type docs).
        intent: Optional human-readable description.
        requested_by: Optional portal/chat username (required for four-eyes unless
            HTTP MCP forwards X-Auth-User / X-OpenClaw-User).
    """
    actor = change_actor.resolve_actor(requested_by)
    _audit(host, "propose_change", f"{change_type} by={actor}")
    return change_engine.propose_change(
        host=host,
        change_type=change_type,
        spec=spec,
        intent=intent,
        created_by=actor,
        get_host=_get_host,
        platform_fn=_platform,
    )


@mcp.tool()
def get_change(change_id: str) -> dict[str, Any]:
    """Return a change record by id (secrets redacted)."""
    _audit("—", "get_change", change_id)
    return change_engine.get_change(change_id, redact=True)


@mcp.tool()
def list_changes(status: str | None = None) -> list[dict[str, Any]]:
    """List change records, optionally filtered by status (proposed, approved, ...)."""
    _audit("—", "list_changes", status or "all")
    return change_engine.list_changes(status=status, redact=True)


@mcp.tool()
def apply_change(change_id: str) -> dict[str, Any]:
    """Apply an approved network change (backup → push → verify → write memory).

    Refuses unless the change status is ``approved``. Approval is only possible
    via the MCP Admin GUI — the agent cannot self-approve.
    """
    _audit("—", "apply_change", change_id)
    return change_engine.apply_change(change_id, actor="mcp")


@mcp.tool()
def rollback_change(change_id: str) -> dict[str, Any]:
    """Roll back a previously applied change using its stored rollback plan."""
    _audit("—", "rollback_change", change_id)
    return change_engine.rollback_change(change_id, actor="mcp")


if __name__ == "__main__":
    _t = os.environ.get("SSH_OPS_MCP_TRANSPORT", "stdio").lower().replace("_", "-")
    if _t in ("http", "streamable-http", "sse"):
        import secrets_store
        import uvicorn
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.responses import JSONResponse

        _auth_on = os.environ.get("SSH_OPS_MCP_AUTH", "1").lower() not in (
            "0", "false", "no", "off", "",
        )
        if _auth_on:
            secrets_store.ensure_mcp_token()

        async def _bearer(request, call_next):
            if not _auth_on:
                change_actor.set_request_actor(
                    change_actor.actor_from_headers(dict(request.headers))
                )
                return await call_next(request)
            hdr = request.headers.get("authorization", "")
            tok = hdr[7:].strip() if hdr[:7].lower() == "bearer " else ""
            if tok and tok in secrets_store.get_mcp_tokens():
                change_actor.set_request_actor(
                    change_actor.actor_from_headers(dict(request.headers))
                )
                return await call_next(request)
            return JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

        _app = mcp.sse_app() if _t == "sse" else mcp.streamable_http_app()
        _app.add_middleware(BaseHTTPMiddleware, dispatch=_bearer)
        _run_kw = dict(
            host=os.environ.get("SSH_OPS_MCP_HOST", "0.0.0.0"),
            port=int(os.environ.get("SSH_OPS_MCP_PORT", "8766")),
        )
        _cert = os.environ.get("SSH_OPS_MCP_TLS_CERT")
        _key = os.environ.get("SSH_OPS_MCP_TLS_KEY")
        if _cert and _key:
            _run_kw["ssl_certfile"] = _cert
            _run_kw["ssl_keyfile"] = _key
        uvicorn.run(_app, **_run_kw)
    else:
        mcp.run()
