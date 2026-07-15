"""Render IOS change artifacts (apply / rollback / verify)."""

from __future__ import annotations

from typing import Any


def normalize_interface_state(spec: dict[str, Any]) -> str:
    state = str(spec.get("state") or "").strip().lower().replace(" ", "_").replace("-", "_")
    if state in ("shut", "shutdown"):
        return "shutdown"
    if state in ("no_shut", "no_shutdown", "noshut"):
        return "no_shutdown"
    return state


def _privilege(spec: dict[str, Any]) -> int:
    try:
        return int(spec.get("privilege", 15))
    except (TypeError, ValueError):
        return 15


def build_ios_local_user_target(host: str, platform: str, spec: dict[str, Any]) -> dict[str, Any]:
    """Build a single network target block for change_store."""
    action = str(spec.get("action") or "create").strip().lower()
    username = str(spec["username"]).strip()

    if action == "delete":
        apply_lines = [f"no username {username}"]
        rollback_lines: list[str] = []
        verify_cmds = [f"show running-config | include ^username {username}"]
        summary = f"Delete IOS local user '{username}' on {host}"
    else:
        secret = str(spec.get("secret") or spec.get("password") or "").strip()
        priv = _privilege(spec)
        apply_lines = [
            f"username {username} privilege {priv} secret {secret}",
        ]
        rollback_lines = [f"no username {username}"]
        verify_cmds = [f"show running-config | include ^username {username}"]
        summary = f"Create IOS local user '{username}' (privilege {priv}) on {host}"

    return {
        "name": host,
        "type": platform,
        "role": "network",
        "summary": summary,
        "apply": apply_lines,
        "rollback": rollback_lines,
        "verify": verify_cmds,
        "verify_expect": "config_present" if action != "delete" else "config_absent",
    }


def build_ios_interface_state_target(host: str, platform: str, spec: dict[str, Any]) -> dict[str, Any]:
    """Build target for interface shutdown / no shutdown."""
    iface = str(spec["interface"]).strip()
    state = normalize_interface_state(spec)

    if state == "shutdown":
        apply_lines = [f"interface {iface}", " shutdown"]
        rollback_lines = [f"interface {iface}", " no shutdown"]
        summary = f"Shutdown interface {iface} on {host}"
        verify_expect = "admin_down"
    else:
        apply_lines = [f"interface {iface}", " no shutdown"]
        rollback_lines = [f"interface {iface}", " shutdown"]
        summary = f"No shutdown interface {iface} on {host}"
        verify_expect = "admin_up"

    verify_cmds = [f"show interfaces {iface} status"]

    return {
        "name": host,
        "type": platform,
        "role": "network",
        "summary": summary,
        "apply": apply_lines,
        "rollback": rollback_lines,
        "verify": verify_cmds,
        "verify_expect": verify_expect,
    }


def build_ios_config_lines_target(host: str, platform: str, spec: dict[str, Any]) -> dict[str, Any]:
    lines = ios_xe_policy.normalize_lines([str(x) for x in (spec.get("lines") or [])])
    group = str(spec.get("group") or spec.get("_policy_group") or "config").strip()
    rollback_lines = list(spec.get("rollback") or [])
    verify_cmds = list(spec.get("verify") or [])
    if not verify_cmds:
        verify_cmds = ["show running-config | include ."]
    summary = spec.get("summary") or f"IOS config ({group}) on {host} — {len(lines)} line(s)"
    return {
        "name": host,
        "type": platform,
        "role": "network",
        "summary": summary,
        "apply": lines,
        "rollback": rollback_lines,
        "verify": verify_cmds,
        "verify_expect": "config_present",
        "policy_group": group,
    }


def public_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Redact secrets for API/GUI responses."""
    out = dict(spec)
    for key in ("password", "secret"):
        if key in out and out[key]:
            out[key] = "***"
    return out
