#!/usr/bin/env python3
"""Validate expanded IOS-XE allow_groups policy."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ssh-ops-mcp"))

import ios_xe_policy


class IosXePolicyGroupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ios_xe_policy._CACHE["mtime"] = None
        os_env = ROOT / "config-templates" / "ios-xe-policy.yaml"
        if os_env.is_file():
            import os

            os.environ["SSH_OPS_IOS_XE_POLICY"] = str(os_env)

    def test_group_count(self) -> None:
        groups = ios_xe_policy.load_policy().get("allow_groups") or {}
        self.assertGreaterEqual(len(groups), 55)

    def test_vlan_l3_still_validates(self) -> None:
        lines = [
            "vlan 51",
            " name MGMT",
            "interface Vlan51",
            " ip address 192.168.51.4 255.255.255.0",
            " no shutdown",
        ]
        risk, errs, _warns, matched = ios_xe_policy.validate_config_lines(
            lines, group="vlan_l3"
        )
        self.assertFalse(errs, errs)
        self.assertEqual(matched, "vlan_l3")
        self.assertEqual(risk, "medium")

    def test_routing_ospf_denied_by_default(self) -> None:
        self.assertEqual(ios_xe_policy.get_group_access("routing_ospf"), "deny")

    def test_aaa_core_denied_by_default(self) -> None:
        self.assertEqual(ios_xe_policy.get_group_access("aaa_core"), "deny")

    def test_netflow_exporter_approvable(self) -> None:
        self.assertEqual(ios_xe_policy.get_group_access("netflow_exporter"), "approve")

    def test_categories_in_gui_list(self) -> None:
        groups = ios_xe_policy.list_groups_for_gui()
        cats = {g["category"] for g in groups}
        self.assertIn("routing", cats)
        self.assertIn("security", cats)
        self.assertIn("qos", cats)
        self.assertIn("netmgmt", cats)


if __name__ == "__main__":
    unittest.main()
