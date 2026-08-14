"""Validate change proposals before they enter the approval queue."""

from __future__ import annotations

import re
from typing import Any

import ios_xe_policy
import verify_spec

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")
PRIVILEGE_MIN = 1
PRIVILEGE_MAX = 15

INTERFACE_RE = re.compile(
    r"^(?:GigabitEthernet|Gi|TenGigabitEthernet|Te|FastEthernet|Fa|Ethernet|Et|"
    r"Port-channel|Po|Vlan|Loopback|Management)\S{0,63}$",
    re.IGNORECASE,
)

ALLOWED_CHANGE_TYPES = frozenset({
    "ios_local_user",
    "ios_interface_state",
    "ios_config_lines",
})


def validate_proposal(
    change_type: str,
    spec: dict[str, Any],
    *,
    platform: str,
) -> tuple[str, list[str], list[str]]:
    """Return (risk, errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []

    if change_type not in ALLOWED_CHANGE_TYPES:
        errors.append(f"Unsupported change_type '{change_type}'.")
        return "high", errors, warnings

    if platform not in ("ios", "ios-xe", "iosxe", "cisco", "cisco_ios", "cisco_xe", "nxos", "cisco_nxos"):
        errors.append(f"change_type '{change_type}' requires a Cisco-class platform (got '{platform}').")

    if change_type == "ios_local_user":
        action = str(spec.get("action") or "create").strip().lower()
        username = str(spec.get("username") or "").strip()
        if not USERNAME_RE.match(username):
            errors.append("spec.username must be 1-32 alphanumeric/._- characters.")
        if action not in ("create", "delete"):
            errors.append("spec.action must be 'create' or 'delete'.")
        if action == "create":
            password = str(spec.get("password") or spec.get("secret") or "").strip()
            if not password:
                errors.append("spec.password (or spec.secret) is required for create.")
            elif len(password) < 8:
                warnings.append("Password shorter than 8 characters.")
            priv = spec.get("privilege", 15)
            try:
                priv_i = int(priv)
            except (TypeError, ValueError):
                errors.append("spec.privilege must be an integer 1-15.")
            else:
                if not PRIVILEGE_MIN <= priv_i <= PRIVILEGE_MAX:
                    errors.append(f"spec.privilege must be between {PRIVILEGE_MIN} and {PRIVILEGE_MAX}.")
            if "password" in spec and "secret" not in spec:
                warnings.append("IOS config will use 'secret' (hashed), not cleartext 'password'.")

    if change_type == "ios_interface_state":
        iface = str(spec.get("interface") or "").strip()
        if not INTERFACE_RE.match(iface):
            errors.append(
                "spec.interface must be a valid IOS interface name "
                "(e.g. GigabitEthernet1/0/1, Gi1/0/1, Port-channel1)."
            )
        state = str(spec.get("state") or "").strip().lower().replace(" ", "_").replace("-", "_")
        if state in ("shut", "shutdown"):
            state = "shutdown"
        elif state in ("no_shut", "no_shutdown", "noshut"):
            state = "no_shutdown"
        if state not in ("shutdown", "no_shutdown"):
            errors.append("spec.state must be 'shutdown' or 'no_shutdown'.")

    if change_type == "ios_config_lines":
        lines = spec.get("lines") or []
        if not isinstance(lines, list):
            errors.append("spec.lines must be a list of config lines.")
        else:
            group = str(spec.get("group") or "").strip() or None
            line_risk, line_errors, line_warnings, matched = ios_xe_policy.validate_config_lines(
                [str(x) for x in lines],
                group=group,
            )
            errors.extend(line_errors)
            warnings.extend(line_warnings)
            if matched and not errors:
                spec["_policy_group"] = matched
                if line_risk in ("high", "medium", "low"):
                    pass  # risk set below
        _verify, verify_errors = verify_spec.parse_verify_input(spec.get("verify"))
        errors.extend(verify_errors)
        _rollback, rollback_errors = verify_spec.parse_rollback_input(spec.get("rollback"))
        errors.extend(rollback_errors)
        _expect, expect_errors = verify_spec.parse_verify_expect(spec.get("verify_expect"))
        errors.extend(expect_errors)

    if change_type == "ios_local_user":
        risk = "high"
    elif change_type == "ios_interface_state":
        risk = "medium"
    elif change_type == "ios_config_lines":
        group = str(spec.get("group") or spec.get("_policy_group") or "").strip()
        grp = (ios_xe_policy.load_policy().get("allow_groups") or {}).get(group) if group else {}
        risk = str(grp.get("risk") if isinstance(grp, dict) else "medium") or "medium"
    else:
        risk = "medium"
    if errors:
        risk = "blocked"
    return risk, errors, warnings
