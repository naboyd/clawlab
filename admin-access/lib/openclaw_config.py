"""Load/save ~/.openclaw/openclaw.json; repair unescaped control chars in strings."""
from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


def default_config_path() -> Path:
    home = Path(os.environ.get("OPENCLAW_HOME", Path.home() / ".openclaw")).expanduser()
    return home / "openclaw.json"


def repair_control_chars_in_strings(raw: str) -> str:
    """Escape raw newlines/tabs/control bytes inside JSON string literals."""
    out: list[str] = []
    in_string = False
    escape = False
    for ch in raw:
        if escape:
            out.append(ch)
            escape = False
            continue
        if in_string and ch == "\\":
            escape = True
            out.append(ch)
            continue
        if ch == '"':
            in_string = not in_string
            out.append(ch)
            continue
        if in_string and ord(ch) < 32:
            if ch == "\n":
                out.append("\\n")
            elif ch == "\r":
                out.append("\\r")
            elif ch == "\t":
                out.append("\\t")
            else:
                out.append(f"\\u{ord(ch):04x}")
            continue
        out.append(ch)
    return "".join(out)


def _print_json_error(path: Path, raw: str, exc: json.JSONDecodeError) -> None:
    print(f"error: invalid JSON in {path}", file=sys.stderr)
    print(f"  {exc.msg} at line {exc.lineno} column {exc.colno}", file=sys.stderr)
    lines = raw.splitlines()
    if exc.lineno and 1 <= exc.lineno <= len(lines):
        bad = lines[exc.lineno - 1]
        print(f"  {bad}", file=sys.stderr)
        if exc.colno:
            print(f"  {' ' * (exc.colno - 1)}^", file=sys.stderr)
    print(
        f"  Try: python3 admin-access/repair-openclaw-json.py",
        file=sys.stderr,
    )


def load_openclaw_json(path: Path, *, repair: bool = True) -> tuple[dict, bool]:
    """Return (config dict, was_repaired)."""
    raw = path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise json.JSONDecodeError("root must be an object", raw, 0)
        return data, False
    except json.JSONDecodeError as exc:
        if not repair:
            _print_json_error(path, raw, exc)
            raise SystemExit(1) from exc
        fixed = repair_control_chars_in_strings(raw)
        try:
            data = json.loads(fixed)
        except json.JSONDecodeError as exc2:
            _print_json_error(path, raw, exc2)
            raise SystemExit(1) from exc2
        if not isinstance(data, dict):
            raise SystemExit(f"error: {path} root must be a JSON object")
        return data, True


def save_openclaw_json(path: Path, cfg: dict, *, backup: bool = True) -> None:
    if backup and path.is_file():
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        shutil.copy2(path, f"{path}.bak-{ts}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
