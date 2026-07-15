"""Load and evaluate IOS-XE configuration policy (shared with DefenseClaw merge)."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_POLICY = _REPO_ROOT / "config-templates" / "ios-xe-policy.yaml"
_POLICY_PATH = Path(
    os.environ.get(
        "SSH_OPS_IOS_XE_POLICY",
        _DEFAULT_POLICY if _DEFAULT_POLICY.is_file() else Path(__file__).parent / "ios-xe-policy.yaml",
    )
).expanduser()

_CACHE: dict[str, Any] = {"mtime": None, "data": None}


def _load_raw() -> dict[str, Any]:
    path = _POLICY_PATH
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
    return str(_POLICY_PATH)


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
        patterns = groups.get(group)
        if not patterns:
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
            errors.append(
                "Config lines do not match any allow_groups entry. "
                f"Known groups: {', '.join(sorted(groups)) or 'none'}."
            )
            return "blocked", errors, warnings, None

    return group_risk, errors, warnings, matched_group
