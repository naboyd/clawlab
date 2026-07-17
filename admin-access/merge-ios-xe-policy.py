#!/usr/bin/env python3
"""Merge IOS-XE policy into DefenseClaw command rules + optional HIGH advisories."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml


def _load(path: Path) -> dict:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    return data if isinstance(data, dict) else {}


def _dump(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, default_flow_style=False))


def defenseclaw_pattern(pat: str) -> str:
    """Adapt IOS-XE line patterns for DefenseClaw tool-arg JSON scanning.

    ``inspectToolPolicy`` scans ``string(req.Args)`` (e.g.
    ``{"command":"reload"}``), not bare config lines. Line-anchored ``^``
    patterns never match inside JSON; use word boundaries like clawlab CMD-* rules.
    """
    raw = str(pat)
    flags = ""
    body = raw
    if body.startswith("(?i)"):
        flags = "(?i)"
        body = body[4:]
    if body.startswith("^"):
        body = body[1:]
        if body.endswith("$"):
            body = body[:-1]
        body = body.removeprefix("\\b")
        if not body.startswith("\\b"):
            body = "\\b" + body
    return flags + body


def merge_command_rules(commands_path: Path, rules: list[dict]) -> int:
    data = _load(commands_path)
    if not data:
        data = {"version": 1, "category": "command", "rules": []}
    existing = [r for r in data.get("rules", []) if isinstance(r, dict)]
    index = {str(r["id"]): i for i, r in enumerate(existing) if r.get("id")}
    changed = 0
    for rule in rules:
        rid = str(rule.get("id") or "")
        if not rid:
            continue
        if rid in index:
            existing[index[rid]] = rule
        else:
            existing.append(rule)
        changed += 1
    data["rules"] = existing
    data["category"] = "command"
    _dump(commands_path, data)
    return changed


def build_rules(policy: dict) -> list[dict]:
    out: list[dict] = []
    for entry in policy.get("always_block") or []:
        if not isinstance(entry, dict):
            continue
        rid = entry.get("id")
        pat = entry.get("pattern")
        if not rid or not pat:
            continue
        out.append({
            "id": str(rid),
            "pattern": defenseclaw_pattern(str(pat)),
            "title": entry.get("title") or str(rid),
            "severity": str(entry.get("severity") or "CRITICAL").upper(),
            "confidence": float(entry.get("confidence") or 0.9),
            "tags": list(entry.get("tags") or ["ios-xe", entry.get("group", "policy"), "block"]),
        })

    for gname, grp in (policy.get("allow_groups") or {}).items():
        if not isinstance(grp, dict):
            continue
        access = str(grp.get("access") or "approve").strip().lower()
        access = access.replace(" ", "_").replace("-", "_")
        if access in ("always_deny", "denied", "block", "blocked"):
            access = "deny"
        elif access in ("always_allow", "allowed", "auto_approve"):
            access = "allow"
        elif access in ("approval_required", "require_approval"):
            access = "approve"

        if access == "deny":
            safe = re.sub(r"[^A-Za-z0-9]+", "-", str(gname)).strip("-").upper()
            for i, pat in enumerate(grp.get("patterns") or []):
                out.append({
                    "id": f"IOS-DENY-{safe}-{i + 1:02d}",
                    "pattern": defenseclaw_pattern(str(pat)),
                    "title": f"IOS-XE config ({gname}): group denied",
                    "severity": "CRITICAL",
                    "confidence": 0.92,
                    "tags": ["ios-xe", gname, "deny", "config"],
                })
            continue
        if not grp.get("defenseclaw_alert"):
            continue
        for i, pat in enumerate(grp.get("patterns") or []):
            safe = re.sub(r"[^A-Za-z0-9]+", "-", str(gname)).strip("-").upper()
            out.append({
                "id": f"IOS-ALERT-{safe}-{i + 1:02d}",
                "pattern": str(pat),
                "title": f"IOS-XE allowed config ({gname}): advisory",
                "severity": "HIGH",
                "confidence": 0.75,
                "tags": ["ios-xe", gname, "advisory", "config"],
            })
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rules-dir", required=True)
    parser.add_argument(
        "--policy",
        default="config-templates/ios-xe-policy.yaml",
        help="Path to ios-xe-policy.yaml",
    )
    args = parser.parse_args()

    repo = Path(__file__).resolve().parent.parent
    policy_path = Path(args.policy)
    if not policy_path.is_absolute():
        policy_path = repo / policy_path
    policy = _load(policy_path)
    if not policy:
        print(f"ERROR: policy not found or empty: {policy_path}", file=sys.stderr)
        return 1

    rules = build_rules(policy)
    commands = Path(args.rules_dir).expanduser() / "commands.yaml"
    n = merge_command_rules(commands, rules)
    print(f"Merged {n} IOS-XE rule(s) into {commands} from {policy_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
