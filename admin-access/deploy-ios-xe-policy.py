#!/usr/bin/env python3
"""Deploy ios-xe-policy.yaml from repo canonical copy to runtime locations."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
CANONICAL = REPO / "config-templates" / "ios-xe-policy.yaml"


def _load(path: Path) -> dict:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    return data if isinstance(data, dict) else {}


def _merge_access(new: dict, old: dict) -> dict:
    old_groups = old.get("allow_groups") or {}
    if not isinstance(old_groups, dict):
        return new
    for name, grp in (new.get("allow_groups") or {}).items():
        if not isinstance(grp, dict):
            continue
        prev = old_groups.get(name)
        if isinstance(prev, dict) and prev.get("access"):
            grp["access"] = prev["access"]
    return new


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, default_flow_style=False))
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def deploy_targets() -> list[Path]:
    paths = [
        REPO / "ssh-ops-mcp" / "ios-xe-policy.yaml",
        Path.home() / "ssh_ops_mcp" / "data" / "ios-xe-policy.yaml",
    ]
    for key in ("IOS_XE_POLICY_PATH", "SSH_OPS_IOS_XE_POLICY"):
        env = os.environ.get(key, "").strip()
        if env:
            paths.append(Path(env).expanduser())
    seen: set[Path] = set()
    out: list[Path] = []
    for path in paths:
        resolved = path.expanduser().resolve()
        if resolved in seen or resolved == CANONICAL.resolve():
            continue
        seen.add(resolved)
        out.append(path)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=CANONICAL,
        help=f"Policy YAML to deploy (default: {CANONICAL})",
    )
    parser.add_argument(
        "--preserve-access",
        action="store_true",
        help="Keep allow_groups.access values from each destination file when group names match",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source = args.source.expanduser()
    if not source.is_file():
        print(f"ERROR: source policy not found: {source}", file=sys.stderr)
        return 1

    base = _load(source)
    if not base.get("allow_groups"):
        print(f"ERROR: source has no allow_groups: {source}", file=sys.stderr)
        return 1

    targets = deploy_targets()
    if not targets:
        print("No deploy targets resolved.")
        return 0

    for dest in targets:
        data = dict(base)
        if args.preserve_access:
            data = _merge_access(data, _load(dest))
        count = len(data.get("allow_groups") or {})
        if args.dry_run:
            print(f"DRY-RUN would write {dest} ({count} groups)")
            continue
        _write(dest, data)
        print(f"Wrote {dest} ({count} groups)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
