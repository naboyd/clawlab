#!/usr/bin/env python3
"""DefenseClaw pattern adaptation for IOS-XE rule merge."""

from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from pathlib import Path

MOD = Path(__file__).resolve().parent.parent / "admin-access" / "merge-ios-xe-policy.py"
spec = importlib.util.spec_from_file_location("merge_ios_xe_policy", MOD)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
defenseclaw_pattern = mod.defenseclaw_pattern


class DefenseclawPatternTests(unittest.TestCase):
    def test_reload_matches_json_tool_args(self) -> None:
        pat = defenseclaw_pattern(r"(?i)^reload\b")
        self.assertRegex('{"command":"reload"}', pat)

    def test_router_ospf_matches_json_tool_args(self) -> None:
        pat = defenseclaw_pattern(r"(?i)^router\s+ospf\b")
        self.assertRegex('{"command":"router ospf 1"}', pat)

    def test_aaa_new_model_matches_json_tool_args(self) -> None:
        pat = defenseclaw_pattern(r"(?i)^aaa\s+new-model\s*$")
        self.assertRegex('{"command":"aaa new-model"}', pat)

    def test_bare_line_still_matches(self) -> None:
        pat = defenseclaw_pattern(r"(?i)^reload\b")
        self.assertRegex("reload", pat)

    def test_non_anchored_pattern_unchanged(self) -> None:
        raw = r"(?i)\buseradd\b"
        self.assertEqual(defenseclaw_pattern(raw), raw)


if __name__ == "__main__":
    unittest.main()
