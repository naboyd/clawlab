#!/usr/bin/env python3
"""Merge Clawlab guardrail extensions into the active DefenseClaw rule pack.

DefenseClaw merges rules/*.yaml by category name; a later file with the same
category replaces the earlier one entirely. Alphabetically, commands.yaml wins
over clawlab-local-user-crud.yaml, so separate command-category files are
silently dropped. This script appends our rules into commands.yaml and intent
patterns into local-patterns.yaml instead.
"""

from __future__ import annotations

import argparse
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


def _rule_ids(rules: list) -> set[str]:
    return {str(r.get("id")) for r in rules if isinstance(r, dict) and r.get("id")}


def merge_command_rules(commands_path: Path, src_path: Path) -> int:
    src = _load(src_path)
    src_rules = [r for r in src.get("rules", []) if isinstance(r, dict) and r.get("id")]
    if not src_rules:
        return 0

    data = _load(commands_path)
    if not data:
        data = {"version": 1, "category": "command", "rules": []}
    rules = [r for r in data.get("rules", []) if isinstance(r, dict)]
    index = {str(r["id"]): i for i, r in enumerate(rules) if r.get("id")}
    added = 0
    updated = 0
    for rule in src_rules:
        rid = str(rule["id"])
        if rid in index:
            rules[index[rid]] = rule
            updated += 1
        else:
            rules.append(rule)
            added += 1
    data["version"] = data.get("version") or 1
    data["category"] = "command"
    data["rules"] = rules
    _dump(commands_path, data)
    return added + updated


def _merge_unique_str_lists(target: list, extra: list) -> tuple[list, int]:
    seen = {str(x) for x in target}
    added = 0
    for item in extra:
        s = str(item)
        if s in seen:
            continue
        target.append(s)
        seen.add(s)
        added += 1
    return target, added


def merge_local_patterns(patterns_path: Path, src_path: Path) -> tuple[int, int]:
    src = _load(src_path)
    if not src:
        return 0, 0

    data = _load(patterns_path)
    if not data:
        data = {"version": 1}

    inj_added = 0
    rx_added = 0
    inj, n = _merge_unique_str_lists(list(data.get("injection") or []), list(src.get("injection") or []))
    inj_added += n
    data["injection"] = inj
    rx, n = _merge_unique_str_lists(
        list(data.get("injection_regexes") or []),
        list(src.get("injection_regexes") or []),
    )
    rx_added += n
    data["injection_regexes"] = rx
    data["version"] = data.get("version") or 1
    _dump(patterns_path, data)
    return inj_added, rx_added


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rules-dir", required=True, help="Target .../guardrail/<pack>/rules")
    parser.add_argument("--src-dir", required=True, help="Clawlab config-templates/guardrail-rules")
    args = parser.parse_args()

    rules_dir = Path(args.rules_dir).expanduser()
    src_dir = Path(args.src_dir).expanduser()
    commands = rules_dir / "commands.yaml"
    patterns = rules_dir / "local-patterns.yaml"
    crud_src = src_dir / "clawlab-local-user-crud.yaml"
    intent_src = src_dir / "clawlab-local-user-intent.yaml"
    c2_src = src_dir / "clawlab-c2-revshell.yaml"

    cmd_changed = merge_command_rules(commands, crud_src)
    if c2_src.is_file():
        cmd_changed += merge_command_rules(commands, c2_src)
    inj_added, rx_added = merge_local_patterns(patterns, intent_src)

    print(f"Merged into {commands}: {cmd_changed} command rule(s) added/updated")
    print(f"Merged into {patterns}: +{inj_added} injection phrase(s), +{rx_added} regex(es)")

    # Remove legacy standalone files that lose to commands.yaml on load.
    for legacy in ("clawlab-local-user-crud.yaml", "clawlab-local-user-intent.yaml", "clawlab-c2-revshell.yaml"):
        legacy_path = rules_dir / legacy
        if legacy_path.is_file():
            legacy_path.unlink()
            print(f"Removed legacy standalone file {legacy_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
