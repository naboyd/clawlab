"""Load and evaluate IOS-XE configuration policy (shared with DefenseClaw merge)."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BUNDLED_POLICY = Path(__file__).parent / "ios-xe-policy.yaml"
_TEMPLATE_POLICY = _REPO_ROOT / "config-templates" / "ios-xe-policy.yaml"
_DATA_POLICY = Path("/data/ios-xe-policy.yaml")

GROUP_ACCESS_MODES = frozenset({"deny", "approve", "allow"})
_DEFAULT_ACCESS = "approve"

_CACHE: dict[str, Any] = {"mtime": None, "data": None}


def _bundled_policy_path() -> Path:
    if _BUNDLED_POLICY.is_file():
        return _BUNDLED_POLICY
    if _TEMPLATE_POLICY.is_file():
        return _TEMPLATE_POLICY
    return _BUNDLED_POLICY


def _resolve_policy_path() -> Path:
    env = os.environ.get("SSH_OPS_IOS_XE_POLICY", "").strip()
    if env:
        return Path(env).expanduser()
    if _DATA_POLICY.parent.is_dir():
        return _DATA_POLICY
    bundled = _bundled_policy_path()
    if bundled.is_file():
        return bundled
    return _TEMPLATE_POLICY if _TEMPLATE_POLICY.is_file() else bundled


_POLICY_PATH = _resolve_policy_path()


def ensure_policy_file() -> Path:
    """Ensure writable policy exists under /data when that volume is mounted."""
    path = _resolve_policy_path()
    if path.is_file():
        return path
    src = _bundled_policy_path()
    if not src.is_file():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    _CACHE["mtime"] = None
    return path


def normalize_access(value: str | None) -> str:
    raw = (value or _DEFAULT_ACCESS).strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "always_deny": "deny",
        "denied": "deny",
        "block": "deny",
        "blocked": "deny",
        "approval_required": "approve",
        "require_approval": "approve",
        "approve": "approve",
        "always_allow": "allow",
        "allowed": "allow",
        "auto_approve": "allow",
    }
    return aliases.get(raw, raw if raw in GROUP_ACCESS_MODES else _DEFAULT_ACCESS)


def _load_raw() -> dict[str, Any]:
    path = ensure_policy_file()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    if _CACHE["mtime"] != mtime:
        try:
            data = yaml.safe_load(path.read_text()) or {}
            _CACHE["data"] = data if isinstance(data, dict) else {}
            _CACHE["mtime"] = mtime
        except Exception:
            pass
    return _CACHE["data"] or {}


def load_policy() -> dict[str, Any]:
    """Return parsed policy document (hot-reloaded on mtime change)."""
    return dict(_load_raw())


def policy_path() -> str:
    return str(ensure_policy_file())


def save_policy(data: dict[str, Any]) -> None:
    """Persist policy YAML and invalidate cache."""
    path = ensure_policy_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, default_flow_style=False))
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    _CACHE["mtime"] = None
    _load_raw()


def get_group_access(group: str | None) -> str:
    if not group:
        return _DEFAULT_ACCESS
    grp = (load_policy().get("allow_groups") or {}).get(group)
    if not isinstance(grp, dict):
        return _DEFAULT_ACCESS
    return normalize_access(str(grp.get("access") or _DEFAULT_ACCESS))


def list_groups_for_gui() -> list[dict[str, Any]]:
    """Summarize allow_groups for the admin Policy tab."""
    data = load_policy()
    out: list[dict[str, Any]] = []
    for name, grp in sorted((data.get("allow_groups") or {}).items()):
        if not isinstance(grp, dict):
            continue
        patterns = grp.get("patterns") or []
        out.append({
            "name": str(name),
            "description": str(grp.get("description") or ""),
            "access": get_group_access(str(name)),
            "risk": str(grp.get("risk") or "medium"),
            "pattern_count": len(patterns) if isinstance(patterns, list) else 0,
        })
    return out


def update_groups_access(updates: dict[str, str]) -> None:
    """Set access mode per allow_group (admin portal)."""
    data = load_policy()
    groups = data.setdefault("allow_groups", {})
    if not isinstance(groups, dict):
        raise ValueError("Policy allow_groups is invalid.")
    for gname, access_raw in updates.items():
        gname = str(gname).strip()
        if not gname or gname not in groups:
            continue
        grp = groups[gname]
        if not isinstance(grp, dict):
            continue
        access = normalize_access(access_raw)
        if access not in GROUP_ACCESS_MODES:
            raise ValueError(f"Invalid access mode for '{gname}': {access_raw!r}")
        grp["access"] = access
    save_policy(data)


def compiled_rules() -> tuple[list[dict[str, Any]], dict[str, list[re.Pattern[str]]]]:
    """Return (always_block rules, allow_groups as compiled regex lists)."""
    data = _load_raw()
    blocks: list[dict[str, Any]] = []
    for entry in data.get("always_block") or []:
        if not isinstance(entry, dict) or not entry.get("pattern"):
            continue
        try:
            blocks.append({**entry, "_re": re.compile(str(entry["pattern"]))})
        except re.error:
            continue

    groups: dict[str, list[re.Pattern[str]]] = {}
    for name, grp in (data.get("allow_groups") or {}).items():
        if not isinstance(grp, dict):
            continue
        if get_group_access(str(name)) == "deny":
            continue
        compiled: list[re.Pattern[str]] = []
        for pat in grp.get("patterns") or []:
            try:
                compiled.append(re.compile(str(pat)))
            except re.error:
                continue
        if compiled:
            groups[str(name)] = compiled
    return blocks, groups


def normalize_lines(lines: list[str]) -> list[str]:
    out: list[str] = []
    for raw in lines:
        line = str(raw).rstrip()
        if line.strip():
            out.append(line)
    return out


def validate_config_lines(
    lines: list[str],
    *,
    group: str | None = None,
) -> tuple[str, list[str], list[str], str | None]:
    """Return (risk, errors, warnings, matched_group)."""
    errors: list[str] = []
    warnings: list[str] = []
    norm = normalize_lines(lines)
    if not norm:
        errors.append("spec.lines must contain at least one config line.")
        return "blocked", errors, warnings, None

    blocks, groups = compiled_rules()
    if not blocks and not groups:
        errors.append(f"IOS-XE policy not loaded from {policy_path()}.")
        return "blocked", errors, warnings, None

    for i, line in enumerate(norm, 1):
        for rule in blocks:
            if rule["_re"].search(line):
                errors.append(
                    f"Line {i} blocked ({rule.get('group', 'policy')}): "
                    f"{rule.get('title', rule.get('id', 'always_block'))}"
                )
                break

    if errors:
        return "blocked", errors, warnings, None

    data = _load_raw()
    mode = str(data.get("mode") or "default_deny").lower()
    if mode != "default_deny":
        warnings.append(f"Policy mode '{mode}' is not implemented; using default_deny.")

    matched_group: str | None = None
    group_risk = "medium"

    if group:
        access = get_group_access(group)
        if access == "deny":
            errors.append(
                f"Config group '{group}' is set to always deny in IOS-XE policy. "
                "Change it to Approval required or Always allow in the Policy tab."
            )
            return "blocked", errors, warnings, None
        patterns = groups.get(group)
        if not patterns:
            if group in (data.get("allow_groups") or {}):
                errors.append(f"Config group '{group}' has no allowed patterns.")
            else:
                errors.append(f"Unknown allow group '{group}'.")
            return "blocked", errors, warnings, None
        for line in norm:
            if not any(p.search(line) for p in patterns):
                errors.append(f"Line not allowed in group '{group}': {line!r}")
        if not errors:
            matched_group = group
            grp_cfg = (data.get("allow_groups") or {}).get(group) or {}
            if isinstance(grp_cfg, dict):
                group_risk = str(grp_cfg.get("risk") or "medium")
    else:
        for gname, patterns in groups.items():
            if all(any(p.search(line) for p in patterns) for line in norm):
                matched_group = gname
                grp_cfg = (data.get("allow_groups") or {}).get(gname) or {}
                if isinstance(grp_cfg, dict):
                    group_risk = str(grp_cfg.get("risk") or "medium")
                break
        if not matched_group:
            denied = [
                n for n, g in (data.get("allow_groups") or {}).items()
                if isinstance(g, dict) and get_group_access(str(n)) == "deny"
            ]
            hint = ""
            if denied:
                hint = f" Denied groups: {', '.join(sorted(denied))}."
            errors.append(
                "Config lines do not match any allowed group. "
                f"Known groups: {', '.join(sorted(groups)) or 'none'}.{hint} "
                "For VLAN + SVI IP on an L3 switch use group vlan_l3."
            )
            return "blocked", errors, warnings, None

    return group_risk, errors, warnings, matched_group
