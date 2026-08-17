#!/usr/bin/env python3
"""Daily IOS running-config archive + out-of-band drift detection."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import ios_config_archive  # noqa: E402


def _default_data_dir() -> Path:
    home = Path.home()
    return home / ".clawlab" / "ssh-ops" / "data"


def _apply_env_defaults() -> None:
    data = _default_data_dir()
    os.environ.setdefault("SSH_OPS_CONFIG", str(data / "hosts.yaml"))
    os.environ.setdefault("SSH_OPS_ENV", str(data / ".env"))
    os.environ.setdefault("SSH_OPS_KEYFILE", str(data / "master.key"))
    os.environ.setdefault(
        "SSH_OPS_CHANGES_DIR",
        str(data / "changes") if (data / "changes").is_dir() else str(data / "changes"),
    )
    os.environ.setdefault("SSH_OPS_IOS_ARCHIVE_DIR", str(data / "ios-config-archive"))
    portal_env = Path.home() / ".claw-portals" / "config.env"
    if portal_env.is_file():
        for line in portal_env.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host",
        help="Check a single host (default: all network hosts in inventory)",
    )
    parser.add_argument(
        "--no-notify",
        action="store_true",
        help="Skip Webex notifications (still archive and diff)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    _apply_env_defaults()
    ios_config_archive.configure_from_env()

    notify = not args.no_notify
    if args.host:
        result = ios_config_archive.check_host_drift(args.host, notify=notify)
        print(json.dumps(result, indent=2))
        return 1 if result.get("error") else 0

    summary = ios_config_archive.run_daily_check(notify=notify)
    print(json.dumps(summary, indent=2))
    return 1 if summary.get("out_of_band") else 0


if __name__ == "__main__":
    raise SystemExit(main())
