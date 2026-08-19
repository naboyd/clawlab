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

    def test_always_block_reload_rejected(self) -> None:
        risk, errs, _warns, matched = ios_xe_policy.validate_config_lines(["reload"])
        self.assertTrue(errs)
        self.assertIn("reload", errs[0].lower())
        self.assertIsNone(matched)
        self.assertEqual(risk, "blocked")

    def test_routing_ospf_explicit_group_rejected(self) -> None:
        risk, errs, _warns, matched = ios_xe_policy.validate_config_lines(
            ["router ospf 1"],
            group="routing_ospf",
        )
        self.assertTrue(errs)
        self.assertIn("always deny", errs[0].lower())
        self.assertIsNone(matched)
        self.assertEqual(risk, "blocked")

    def test_aaa_core_line_blocked(self) -> None:
        risk, errs, _warns, matched = ios_xe_policy.validate_config_lines(
            ["aaa new-model"],
            group="aaa_core",
        )
        self.assertTrue(errs)
        self.assertIsNone(matched)

    def test_netflow_exporter_lines_valid(self) -> None:
        lines = ["flow exporter EXPORTER1", " destination 192.168.1.1"]
        risk, errs, _warns, matched = ios_xe_policy.validate_config_lines(
            lines,
            group="netflow_exporter",
        )
        self.assertFalse(errs, errs)
        self.assertEqual(matched, "netflow_exporter")

    def test_qos_class_map_exists(self) -> None:
        groups = ios_xe_policy.load_policy().get("allow_groups") or {}
        self.assertIn("qos_class_map", groups)
        self.assertIn("acl_extended", groups)

    def test_ip_helpers_update_lines_valid(self) -> None:
        lines = [
            "interface Vlan100",
            " no ip helper-address 10.0.0.1",
            " ip helper-address 10.0.0.2",
        ]
        risk, errs, _warns, matched = ios_xe_policy.validate_config_lines(
            lines,
            group="ip_helpers",
        )
        self.assertFalse(errs, errs)
        self.assertEqual(matched, "ip_helpers")
        self.assertEqual(risk, "medium")
        self.assertEqual(ios_xe_policy.get_group_access("ip_helpers"), "approve")

    def test_wlan_create_validates(self) -> None:
        lines = [
            "wlan lab-wlan 10 LabSSID",
            " no shutdown",
            "wireless profile policy lab-wlan-policy",
            " vlan 100",
            " no shutdown",
            "wireless tag policy default-policy-tag",
            " wlan lab-wlan policy lab-wlan-policy",
        ]
        risk, errs, _warns, matched = ios_xe_policy.validate_config_lines(
            lines,
            group="wlan_create",
        )
        self.assertFalse(errs, errs)
        self.assertEqual(matched, "wlan_create")
        self.assertEqual(risk, "high")
        self.assertEqual(ios_xe_policy.get_group_access("wlan_create"), "approve")


if __name__ == "__main__":
    unittest.main()
