#!/usr/bin/env python3
"""One-shot scrub of personal/lab identifiers before public release.

  python3 admin-access/scrub-public-release.py --check   # dry-run counts
  python3 admin-access/scrub-public-release.py --apply   # rewrite tracked text files
"""
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Order matters: longer / more specific patterns first.
REPLACEMENTS: list[tuple[str, str]] = [
    ("icecream.naboydciscolab.com", "lab.example.com"),
    ("github.com/nabboyd/clawlab", "github.com/cisco/clawlab"),
    ("192.168.128.93", "192.168.1.10"),
    ("192.168.128.42", "192.168.1.42"),
    ("192.168.128.10", "192.168.1.10"),
    ("192.168.128.4", "192.168.1.4"),
    ("/Users/naboyd/AI/clawlab", "${CLAWLAB_REPO}"),
    ("/home/naboyd", "/home/clawlab"),
    ("boydn@me.com", "admin@example.com"),
    ("SUDO_USER:-${USER:-naboyd}}", "SUDO_USER:-${USER:-clawlab}}"),
    ("enable-linger naboyd", "enable-linger clawlab"),
    ("reset-icecream-portal", "reset-lab-portal"),
    ("hannah-specialist-network-v2:latest", "network-specialist:latest"),
    ("hannah-network-v2", "training-network-specialist"),
    ("You are Hannah,", "You are a network operations agent,"),
    ("You are Hannah using", "You are a network operations agent using"),
    ("legacy icecream redeploy, Alice/Hannah training benches",
     "legacy lab redeploy and maintainer training benches"),
    ("admin-access/hannah-network-v2/**", "admin-access/training-network-specialist/**"),
    ("Alice/Hannah training", "maintainer training"),
    ("Icecream-specific", "Lab-host-specific"),
    ("like icecream, no LE", "like a Linux lab host, no LE"),
    ("like icecream, re-run", "with portal + MCP, re-run"),
    ("vs install-portals.sh / icecream production path",
     "vs install-portals.sh / Linux HTTPS production path"),
    ("deploy portals on icecream", "deploy portals on your Linux lab host"),
    ("user@icecream", "user@lab-host"),
    ("HOST=\"icecream\"", 'HOST="lab-host"'),
    ("HOST=icecream", "HOST=lab-host"),
    ("else icecream", "else lab-host"),
    ("default `icecream`", "default `lab-host`"),
    ("default: first linux host in hosts.yaml, else icecream on Linux lab",
     "default: first linux host in hosts.yaml, else lab-host on Linux lab"),
    ("on host **icecream**", "on a **Linux lab host**"),
    ("around the OpenClaw agent on `icecream`",
     "around the OpenClaw agent on the lab host"),
    ("### On icecream (full stack)", "### On the Linux lab host (full stack)"),
    ("Lab host redeploy (icecream)", "Lab host redeploy"),
    ("(icecream lab)", "(lab host)"),
    ("From icecream after git pull", "From the lab host after git pull"),
    ("Key paths on icecream", "Key paths on the lab host"),
    ("nginx on icecream ->", "nginx on lab host ->"),
    ("# Requires:    sudo loginctl enable-linger naboyd",
     "# Requires:    sudo loginctl enable-linger $USER"),
    ("server_name icecream ", "server_name lab-host "),
    ("server_name icecream\n", "server_name lab-host\n"),
    ("https://icecream:", "https://lab-host:"),
    (" vs icecream.naboydciscolab.com", " vs lab.example.com"),
    (" icecream ", " lab-host "),
    ("| **icecream**", "| **lab-host**"),
    ("host **icecream**", "host **lab-host**"),
    ("after step 2 (icecream production path)", "after step 2 (Linux HTTPS production path)"),
    ("**Linux lab server (icecream):**", "**Linux lab server:**"),
    ("(self-contained, like icecream without LE)", "(self-contained Linux lab without LE)"),
]

SKIP_DIRS = {".git", ".tmp", "__pycache__", "node_modules", "_archive"}
SKIP_SUFFIXES = {".png", ".pdf", ".pyc", ".db", ".jsonl"}


def tracked_files() -> list[Path]:
    out = subprocess.check_output(["git", "ls-files"], cwd=REPO, text=True)
    return [REPO / line for line in out.splitlines() if line.strip()]


def should_scrub(path: Path) -> bool:
    if any(part in SKIP_DIRS for part in path.parts):
        return False
    if path.suffix.lower() in SKIP_SUFFIXES:
        return False
    return path.is_file()


def scrub_text(text: str) -> str:
    for old, new in REPLACEMENTS:
        text = text.replace(old, new)
    return text


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if not args.apply and not args.check:
        ap.error("pass --check or --apply")

    hits = 0
    changed = 0
    for path in tracked_files():
        if not should_scrub(path):
            continue
        try:
            original = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        updated = scrub_text(original)
        if updated != original:
            changed += 1
            hits += sum(
                len(re.findall(re.escape(old), original))
                for old, _ in REPLACEMENTS
                if old in original
            )
            if args.apply:
                path.write_text(updated, encoding="utf-8")
    mode = "APPLY" if args.apply else "CHECK"
    print(f"{mode}: {changed} file(s) would change / changed")


if __name__ == "__main__":
    main()
