"""Validate and normalize IOS change verify / rollback specifications."""

from __future__ import annotations

import re
from typing import Any

VERIFY_EXPECT_VALUES = frozenset({"config_present", "config_absent", "admin_up", "admin_down"})
IOS_CONFIG_VERIFY_EXPECT = frozenset({"config_present", "config_absent"})
STRUCTURED_EXPECT_KEYS = (
    "expect_contains",
    "expect_not_contains",
    "expect_empty",
    "expect_regex",
)


def _helpful_verify_shape_error() -> str:
    return (
        "verify must be a non-empty string, a list of CLI command strings, or a list of "
        "objects like "
        '{"command": "show run | include foo", "expect_contains": "foo"}. '
        "A bare object at the top level is not accepted — wrap it in a list."
    )


def parse_verify_expect(raw: Any, *, allowed: frozenset[str] | None = None) -> tuple[str, list[str]]:
    allowed = allowed or IOS_CONFIG_VERIFY_EXPECT
    default = "config_present"
    if raw is None:
        return default, []
    value = str(raw).strip().lower().replace(" ", "_").replace("-", "_")
    if value not in allowed:
        return default, [
            f"spec.verify_expect must be one of {sorted(allowed)!r} (got {raw!r})."
        ]
    return value, []


def _validate_structured_entry(item: dict[str, Any], index: int) -> list[str]:
    errors: list[str] = []
    cmd = str(item.get("command") or "").strip()
    if not cmd:
        errors.append(f"verify[{index}] object must include a non-empty 'command' string.")
    present = [k for k in STRUCTURED_EXPECT_KEYS if k in item]
    if len(present) != 1:
        errors.append(
            f"verify[{index}] object must include exactly one of "
            f"{list(STRUCTURED_EXPECT_KEYS)!r}."
        )
    if "expect_empty" in item and not isinstance(item.get("expect_empty"), bool):
        errors.append(f"verify[{index}].expect_empty must be a boolean.")
    if "expect_regex" in item:
        try:
            re.compile(str(item["expect_regex"]))
        except re.error as exc:
            errors.append(f"verify[{index}].expect_regex is invalid: {exc}")
    return errors


def _normalize_structured(item: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"command": str(item["command"]).strip()}
    for key in STRUCTURED_EXPECT_KEYS:
        if key in item:
            out[key] = item[key]
    return out


def parse_verify_input(raw: Any) -> tuple[list[Any], list[str]]:
    """Return normalized verify list (strings or structured dicts) and errors."""
    errors: list[str] = []
    if raw is None:
        return [], errors
    if isinstance(raw, str):
        cmd = raw.strip()
        if not cmd:
            return [], ["verify string must be non-empty."]
        return [cmd], errors
    if isinstance(raw, dict):
        return [], [_helpful_verify_shape_error()]
    if not isinstance(raw, list):
        return [], [_helpful_verify_shape_error()]
    if not raw:
        return [], ["verify list must contain at least one entry when provided."]

    out: list[Any] = []
    for idx, item in enumerate(raw, 1):
        if isinstance(item, str):
            cmd = item.strip()
            if not cmd:
                errors.append(f"verify[{idx}] must be a non-empty string.")
                continue
            out.append(cmd)
            continue
        if isinstance(item, dict):
            item_errors = _validate_structured_entry(item, idx)
            if item_errors:
                errors.extend(item_errors)
                continue
            out.append(_normalize_structured(item))
            continue
        errors.append(f"verify[{idx}] must be a string or structured object.")
    if not out and not errors:
        errors.append("verify list did not contain any valid entries.")
    return out, errors


def parse_rollback_input(raw: Any) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    if raw is None:
        return [], errors
    if not isinstance(raw, list):
        return [], ["rollback must be a list of config lines."]
    out: list[str] = []
    for idx, item in enumerate(raw, 1):
        line = str(item).strip()
        if not line:
            errors.append(f"rollback[{idx}] must be a non-empty string.")
            continue
        out.append(str(item).rstrip())
    return out, errors


def invert_verify_expect(expect: str | None) -> str:
    value = str(expect or "config_present").strip().lower()
    if value == "config_present":
        return "config_absent"
    if value == "config_absent":
        return "config_present"
    if value == "admin_up":
        return "admin_down"
    if value == "admin_down":
        return "admin_up"
    return value


def invert_verify_entry(entry: Any) -> Any:
    """Invert structured verify entry for rollback; plain strings rely on verify_expect flip."""
    if isinstance(entry, str):
        return entry
    if not isinstance(entry, dict):
        return entry
    out: dict[str, Any] = {"command": str(entry.get("command") or "").strip()}
    if "expect_contains" in entry:
        out["expect_not_contains"] = entry["expect_contains"]
    elif "expect_not_contains" in entry:
        out["expect_contains"] = entry["expect_not_contains"]
    elif entry.get("expect_empty") is True:
        out["expect_empty"] = False
    elif entry.get("expect_empty") is False:
        out["expect_empty"] = True
    elif "expect_regex" in entry:
        out["expect_not_regex"] = entry["expect_regex"]
    elif "expect_not_regex" in entry:
        out["expect_regex"] = entry["expect_not_regex"]
    else:
        return dict(entry)
    return out


def invert_verify_list(entries: list[Any]) -> list[Any]:
    return [invert_verify_entry(entry) for entry in entries]
