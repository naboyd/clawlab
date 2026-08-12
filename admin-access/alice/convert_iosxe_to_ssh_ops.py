#!/usr/bin/env python3
"""
Convert IOS-XE collected training JSONL to Alice ssh-ops run_command tool_calls format.

Usage:
  python3 admin-access/alice/convert_iosxe_to_ssh_ops.py
  python3 admin-access/alice/convert_iosxe_to_ssh_ops.py --input 'field_definitions/ios_xe_*.jsonl'
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def hannai_training_dir() -> Path:
    return Path(
        os.environ.get(
            "HANNAI_OPS_TRAINING",
            Path.home() / "ai" / "hannai-ops" / "training",
        )
    ).expanduser()

ALICE_SYSTEM = (
    "You are Alice using clawlab ssh-ops MCP from OpenClaw. Use run_command(host, command) "
    "with host names from list_hosts. Never use legacy ios_* tools or fake tool_response blocks. "
    "Summarize only tool output; do not invent VLANs, routes, or protocols."
)

# Optional map from collected device id -> ssh-ops hosts.yaml name
HOST_ALIASES = {
    "192.168.1.42": "c9300-24-office",
    "192.168.1.10": "lab.example.com",
}


def tc(name: str, arguments: dict) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(arguments, separators=(",", ":")),
        },
    }


def resolve_host(device: str) -> str:
    device = (device or "").strip()
    return HOST_ALIASES.get(device, device)


def convert_messages(messages: list[dict]) -> list[dict] | None:
    """Return converted messages or None if row cannot be converted."""
    out: list[dict] = [{"role": "system", "content": ALICE_SYSTEM}]
    i = 0
    while i < len(messages):
        msg = messages[i]
        role = msg.get("role")
        if role == "system":
            i += 1
            continue
        if role == "user":
            out.append(msg)
            i += 1
            continue
        if role == "tool":
            try:
                payload = json.loads(msg.get("content") or "{}")
            except json.JSONDecodeError:
                return None
            command = payload.get("command")
            device = payload.get("device") or payload.get("host")
            output = payload.get("output") or payload.get("stdout") or ""
            if not command or not device:
                return None
            host = resolve_host(str(device))
            out.append(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        tc("run_command", {"host": host, "command": command})
                    ],
                }
            )
            out.append(
                {
                    "role": "tool",
                    "content": json.dumps(
                        {
                            "host": host,
                            "command": command,
                            "stdout": output[:8000],
                            "exit_code": 0,
                        },
                        ensure_ascii=False,
                    ),
                }
            )
            i += 1
            # Optional following assistant summary
            if i < len(messages) and messages[i].get("role") == "assistant":
                out.append(messages[i])
                i += 1
            continue
        if role == "assistant":
            # Already has tool_calls — pass through if using run_command
            if msg.get("tool_calls"):
                out.append(msg)
            else:
                out.append(msg)
            i += 1
            continue
        i += 1
    if len(out) < 3:
        return None
    return out


def convert_file(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        converted = convert_messages(obj.get("messages") or [])
        if converted:
            rows.append({"messages": converted})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default=None,
        help="Glob of IOS-XE JSONL files (default: HANNAI_OPS_TRAINING/field_definitions/ios_xe_*.jsonl)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=SCRIPT_DIR / "training" / "iosxe_ssh_ops_converted.jsonl",
    )
    args = parser.parse_args()
    training = hannai_training_dir()
    input_glob = args.input or str(
        training / "field_definitions" / "ios_xe_routing_and_cli_format_*.jsonl"
    )

    paths = sorted(Path(p) for p in glob.glob(input_glob))
    if not paths:
        print(f"No input files match: {input_glob}", file=sys.stderr)
        args.output.write_text("", encoding="utf-8")
        return 0

    all_rows: list[dict] = []
    for path in paths:
        chunk = convert_file(path)
        print(f"{path.name}: converted {len(chunk)} rows", file=sys.stderr)
        all_rows.extend(chunk)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as fh:
        for row in all_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"Wrote {len(all_rows)} rows -> {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
