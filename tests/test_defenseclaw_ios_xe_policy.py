#!/usr/bin/env python3
"""DefenseClaw webgui ios-xe-policy helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "defenseclaw-webgui"))

import policy_store as ps  # noqa: E402


class DefenseclawIosXePolicyTests(unittest.TestCase):
    def test_canonical_policy_path_in_repo(self) -> None:
        path = ps.ios_xe_policy_path()
        self.assertTrue(path.is_file(), f"missing policy: {path}")
        self.assertIn("ios-xe-policy.yaml", path.name)

    def test_summary_counts_groups(self) -> None:
        data = ps.load_yaml_file(ps.ios_xe_policy_path())
        summary = ps.ios_xe_policy_summary(data)
        self.assertGreaterEqual(summary["group_count"], 55)
        self.assertGreater(len(summary["categories"]), 5)

    def test_validate_rejects_empty_groups(self) -> None:
        ok, msg = ps.validate_ios_xe_policy({"allow_groups": {}})
        self.assertFalse(ok)
        self.assertIn("allow_groups", msg)


if __name__ == "__main__":
    unittest.main()
