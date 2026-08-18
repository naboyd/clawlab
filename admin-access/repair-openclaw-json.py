#!/usr/bin/env python3
"""Repair common openclaw.json corruption (unescaped control chars in strings)."""
from __future__ import annotations

import sys
from pathlib import Path

LIB = Path(__file__).resolve().parent / "lib"
sys.path.insert(0, str(LIB))

from openclaw_config import default_config_path, load_openclaw_json, save_openclaw_json  # noqa: E402


def main() -> int:
    path = default_config_path()
    if not path.is_file():
        print(f"Missing {path}", file=sys.stderr)
        return 1
    cfg, repaired = load_openclaw_json(path, repair=True)
    if not repaired:
        print(f"OK: {path} is valid JSON")
        return 0
    save_openclaw_json(path, cfg, backup=True)
    print(f"Repaired and saved {path} (backup: {path}.bak-*)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
