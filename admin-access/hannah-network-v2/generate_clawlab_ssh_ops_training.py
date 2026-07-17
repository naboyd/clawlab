#!/usr/bin/env python3
"""
Generate OpenAI/Qwen tool-calling training JSONL for clawlab ssh-ops MCP (OpenClaw).

Reads tool names from clawlab ssh-ops-mcp/server.py (via CLAWLAB_REPO) and emits
hand-crafted multi-turn examples using list_hosts / run_command — the schema
OpenClaw actually exposes (not legacy ios_get_* hannai-ops tools).

Usage:
  python clawlab-ssh-ops/generate_clawlab_ssh_ops_training.py
  CLAWLAB_REPO=~/clawlab python clawlab-ssh-ops/generate_clawlab_ssh_ops_training.py -o out.jsonl
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
CLAWLAB_REPO_DEFAULT = SCRIPT_DIR.parent.parent  # admin-access/hannah-network-v2 -> clawlab root


def resolve_clawlab_repo(explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if (p / "ssh-ops-mcp" / "server.py").is_file():
            return p
        raise SystemExit(f"CLAWLAB_REPO invalid (no ssh-ops-mcp/server.py): {p}")
    for candidate in (
        CLAWLAB_REPO_DEFAULT,
        Path.home() / "clawlab",
        Path.home() / "AI" / "clawlab",
        Path.home() / "ai" / "hannai-ops" / ".." / "clawlab",
    ):
        c = candidate.expanduser().resolve()
        if (c / "ssh-ops-mcp" / "server.py").is_file():
            return c
    raise SystemExit(
        "Set CLAWLAB_REPO to your clawlab checkout (needs ssh-ops-mcp/server.py)."
    )


def discover_ssh_ops_tools(server_py: Path) -> list[str]:
    """Parse @mcp.tool() function names from server.py."""
    src = server_py.read_text(encoding="utf-8")
    tree = ast.parse(src)
    tools: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and getattr(dec.func, "attr", None) == "tool":
                tools.append(node.name)
                break
            if isinstance(dec, ast.Attribute) and dec.attr == "tool":
                tools.append(node.name)
                break
    return sorted(set(tools))


CLAWLAB_SYSTEM = (
    "You are Hannah, an AI network engineer using the clawlab ssh-ops MCP from OpenClaw. "
    "Always invoke tools via tool_calls (never print fake syntax like ssh-ops__run_command in prose). "
    "Host names must come from list_hosts — use the configured name (e.g. C9300-24P), not invented labels. "
    "On Cisco IOS/IOS-XE use read-only show/dir/ping/traceroute via run_command unless the user explicitly "
    "requests a gated change (then propose_change). "
    "For a specific VLAN id N prefer: show vlan id N and show interfaces status | include VlanN — "
    "do NOT use show vlan brief | include VLAN99 (wrong filter text). "
    "Present ONLY data returned by tools. TRUTH > COMPLETENESS."
)


def tc(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(arguments, separators=(",", ":")),
        },
    }


def example(messages: list[dict[str, Any]]) -> dict[str, Any]:
    if messages[0].get("role") != "system":
        messages = [{"role": "system", "content": CLAWLAB_SYSTEM}, *messages]
    return {"messages": messages}


def build_examples() -> list[dict[str, Any]]:
    hosts_sample = [
        {"name": "C9300-24P", "kind": "network", "platform": "cisco_ios", "allow_write": True},
        {"name": "Nuc03", "kind": "linux", "platform": "linux", "allow_write": False},
        {"name": "icecream.naboydciscolab.com", "kind": "linux", "auto_update": True},
        {"name": "c9800l", "kind": "network", "platform": "cisco_ios"},
    ]

    vlan99_detail = (
        "VLAN Name                             Status    Ports\n"
        "---- -------------------------------- --------- -------------------------------\n"
        "99   VLAN0099                         active    Gi1/0/10, Gi1/0/11"
    )
    int_status_vlan99 = (
        "Port         Name               Status       Vlan       Duplex  Speed Type\n"
        "Gi1/0/10     access-user        connected    99         a-full  a-1000 10/100/1000BaseTX\n"
        "Gi1/0/11     guest-port         notconnect   99         auto    auto   10/100/1000BaseTX"
    )

    ex: list[dict[str, Any]] = []

    ex.append(
        example(
            [
                {"role": "user", "content": "Use ssh-ops to list configured hosts. Reply with host names only."},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [tc("list_hosts", {})],
                },
                {"role": "tool", "content": json.dumps(hosts_sample)},
                {
                    "role": "assistant",
                    "content": "Configured hosts: C9300-24P, Nuc03, icecream.naboydciscolab.com, c9800l.",
                },
            ]
        )
    )

    ex.append(
        example(
            [
                {
                    "role": "user",
                    "content": "On C9300-24P, show vlan 99 and whether any interface is assigned. Read-only ssh-ops only.",
                },
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        tc("run_command", {"host": "C9300-24P", "command": "show vlan id 99"})
                    ],
                },
                {
                    "role": "tool",
                    "content": json.dumps(
                        {
                            "host": "C9300-24P",
                            "command": "show vlan id 99",
                            "stdout": vlan99_detail,
                            "exit_code": 0,
                        }
                    ),
                },
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        tc(
                            "run_command",
                            {
                                "host": "C9300-24P",
                                "command": "show interfaces status | include Vlan99",
                            },
                        )
                    ],
                },
                {
                    "role": "tool",
                    "content": json.dumps(
                        {
                            "host": "C9300-24P",
                            "command": "show interfaces status | include Vlan99",
                            "stdout": int_status_vlan99,
                            "exit_code": 0,
                        }
                    ),
                },
                {
                    "role": "assistant",
                    "content": (
                        "**VLAN 99** on C9300-24P is active (name VLAN0099).\n\n"
                        "**Interfaces assigned:** Gi1/0/10 (connected, access), Gi1/0/11 (notconnect, VLAN 99)."
                    ),
                },
            ]
        )
    )

    ex.append(
        example(
            [
                {"role": "user", "content": "Show IOS version on C9300-24P via ssh-ops."},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        tc("run_command", {"host": "C9300-24P", "command": "show version"})
                    ],
                },
                {
                    "role": "tool",
                    "content": json.dumps(
                        {
                            "host": "C9300-24P",
                            "command": "show version",
                            "stdout": "Cisco IOS XE Software, Version 17.12.04\nC9300-24P uptime is 2 weeks, 3 days",
                            "exit_code": 0,
                        }
                    ),
                },
                {
                    "role": "assistant",
                    "content": "C9300-24P runs **IOS-XE 17.12.04**. Uptime about 2 weeks, 3 days (from show version).",
                },
            ]
        )
    )

    ex.append(
        example(
            [
                {"role": "user", "content": "Show ip interface brief on c9300-24-office (read only)."},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        tc(
                            "run_command",
                            {
                                "host": "c9300-24-office",
                                "command": "show ip interface brief",
                            },
                        )
                    ],
                },
                {
                    "role": "tool",
                    "content": json.dumps(
                        {
                            "host": "c9300-24-office",
                            "command": "show ip interface brief",
                            "stdout": "Interface              IP-Address      OK? Method Status                Protocol\nVlan1                  192.168.128.10  YES NVRAM  up                    up",
                            "exit_code": 0,
                        }
                    ),
                },
                {
                    "role": "assistant",
                    "content": "Vlan1 is up/up with IP 192.168.128.10 on c9300-24-office (from show ip interface brief).",
                },
            ]
        )
    )

    ex.append(
        example(
            [
                {"role": "user", "content": "On C9300-24P run show run | include ntp"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        tc(
                            "run_command",
                            {"host": "C9300-24P", "command": "show run | include ntp"},
                        )
                    ],
                },
                {
                    "role": "tool",
                    "content": json.dumps(
                        {
                            "host": "C9300-24P",
                            "command": "show run | include ntp",
                            "stdout": "ntp server 192.168.128.4",
                            "exit_code": 0,
                        }
                    ),
                },
                {
                    "role": "assistant",
                    "content": "NTP config on C9300-24P: ntp server 192.168.128.4",
                },
            ]
        )
    )

    ex.append(
        example(
            [
                {
                    "role": "user",
                    "content": "Check openclaw-gateway status on icecream.naboydciscolab.com (read only).",
                },
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        tc(
                            "run_command",
                            {
                                "host": "icecream.naboydciscolab.com",
                                "command": "systemctl --user is-active openclaw-gateway",
                            },
                        )
                    ],
                },
                {
                    "role": "tool",
                    "content": json.dumps(
                        {
                            "host": "icecream.naboydciscolab.com",
                            "command": "systemctl --user is-active openclaw-gateway",
                            "stdout": "active",
                            "exit_code": 0,
                        }
                    ),
                },
                {
                    "role": "assistant",
                    "content": "openclaw-gateway is **active** on icecream.naboydciscolab.com.",
                },
            ]
        )
    )

    # Negative: wrong IOS filter — model should not repeat; teach correct command
    ex.append(
        example(
            [
                {
                    "role": "system",
                    "content": CLAWLAB_SYSTEM
                    + " If a command returns a syntax error, try a different read-only show command — "
                    "never echo ssh-ops__run_command in markdown.",
                },
                {"role": "user", "content": "On C9300-24P, is vlan 99 present?"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        tc("run_command", {"host": "C9300-24P", "command": "show vlan id 99"})
                    ],
                },
                {
                    "role": "tool",
                    "content": json.dumps(
                        {
                            "host": "C9300-24P",
                            "command": "show vlan id 99",
                            "stdout": vlan99_detail,
                            "exit_code": 0,
                        }
                    ),
                },
                {
                    "role": "assistant",
                    "content": "Yes — VLAN 99 (VLAN0099) is active on C9300-24P with ports Gi1/0/10 and Gi1/0/11.",
                },
            ]
        )
    )

    # Negative: do not use run_write_command for show
    ex.append(
        example(
            [
                {
                    "role": "user",
                    "content": "Run show vlan brief on C9300-24P. Do not make config changes.",
                },
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        tc(
                            "run_command",
                            {"host": "C9300-24P", "command": "show vlan brief"},
                        )
                    ],
                },
                {
                    "role": "tool",
                    "content": json.dumps(
                        {
                            "host": "C9300-24P",
                            "command": "show vlan brief",
                            "stdout": "VLAN Name                             Status    Ports\n1    default                          active    Gi1/0/1",
                            "exit_code": 0,
                        }
                    ),
                },
                {
                    "role": "assistant",
                    "content": "show vlan brief on C9300-24P returned VLAN 1 (default) active on Gi1/0/1. Read-only command only — no writes.",
                },
            ]
        )
    )

    # propose_change awareness (no apply)
    ex.append(
        example(
            [
                {
                    "role": "user",
                    "content": "Add a local user on C9300-24P — propose only, do not apply.",
                },
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        tc(
                            "propose_change",
                            {
                                "host": "C9300-24P",
                                "change_type": "ios_local_user",
                                "spec": {
                                    "username": "netops-ro",
                                    "action": "create",
                                    "privilege": 1,
                                },
                                "intent": "Add read-only local operator account",
                                "requested_by": "alice",
                            },
                        )
                    ],
                },
                {
                    "role": "tool",
                    "content": json.dumps(
                        {
                            "change_id": "chg-001",
                            "status": "proposed",
                            "host": "C9300-24P",
                        }
                    ),
                },
                {
                    "role": "assistant",
                    "content": (
                        "Proposed change **chg-001** (status: proposed) for ios_local_user on C9300-24P. "
                        "A human must approve in MCP Admin before apply_change."
                    ),
                },
            ]
        )
    )

    # check_health on linux
    ex.append(
        example(
            [
                {"role": "user", "content": "Is Nuc03 healthy? Use ssh-ops check_health."},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [tc("check_health", {"host": "Nuc03"})],
                },
                {
                    "role": "tool",
                    "content": json.dumps(
                        {"host": "Nuc03", "healthy": True, "checks": {"disk": "ok", "load": "ok"}}
                    ),
                },
                {
                    "role": "assistant",
                    "content": "Nuc03 health check passed (disk ok, load ok).",
                },
            ]
        )
    )

    return ex


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate clawlab ssh-ops training JSONL")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=SCRIPT_DIR / "clawlab_ssh_ops_training.jsonl",
        help="Output JSONL path",
    )
    parser.add_argument(
        "--clawlab-repo",
        default=None,
        help="Path to clawlab repo (or set CLAWLAB_REPO)",
    )
    args = parser.parse_args()

    repo = resolve_clawlab_repo(args.clawlab_repo or __import__("os").environ.get("CLAWLAB_REPO"))
    server_py = repo / "ssh-ops-mcp" / "server.py"
    tools = discover_ssh_ops_tools(server_py)
    print(f"clawlab repo: {repo}", file=sys.stderr)
    print(f"ssh-ops tools ({len(tools)}): {', '.join(tools)}", file=sys.stderr)

    examples = build_examples()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as fh:
        for row in examples:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    manifest = {
        "source": str(server_py),
        "tools_discovered": tools,
        "examples_written": len(examples),
        "output": str(args.output),
    }
    (SCRIPT_DIR / "clawlab_ssh_ops_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote {len(examples)} examples -> {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
