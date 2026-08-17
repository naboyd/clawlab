"""Tests for DHCP change builder and policy."""

from __future__ import annotations

import unittest

import change_policy
import dhcp_change


class DhcpChangeTests(unittest.TestCase):
    def test_build_target(self) -> None:
        target = dhcp_change.build_dhcp_include_target(
            "Services",
            {
                "include_name": "vlan100.conf",
                "content": "subnet 10.100.0.0 netmask 255.255.255.0 {}\n",
            },
        )
        self.assertEqual(target["type"], "dhcp_sidecar")
        self.assertEqual(target["include_name"], "vlan100.conf")
        self.assertIn("content", target["apply"])

    def test_policy_accepts_dhcp_include(self) -> None:
        risk, errors, _warnings = change_policy.validate_proposal(
            "dhcp_include",
            {
                "include_name": "vlan100.conf",
                "content": "subnet 10.100.0.0 netmask 255.255.255.0 {}\n",
            },
            platform="linux",
        )
        self.assertFalse(errors, errors)
        self.assertEqual(risk, "medium")

    def test_policy_rejects_ios_platform(self) -> None:
        _risk, errors, _warnings = change_policy.validate_proposal(
            "dhcp_include",
            {"include_name": "vlan100.conf", "content": "subnet 10.0.0.0 netmask 255.255.255.0 {}\n"},
            platform="ios-xe",
        )
        self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
