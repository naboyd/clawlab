"""Tests for dhcp-sidecar operations."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest import mock

import dhcp_ops


class DhcpOpsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(os.environ["TEST_TMPDIR"]) if "TEST_TMPDIR" in os.environ else None
        import tempfile

        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        self.includes = root / "includes"
        self.state = root / "state"
        self.includes.mkdir()
        self.state.mkdir()
        fake_bin = root / "bin"
        fake_bin.mkdir()
        fake_dhcpd = fake_bin / "dhcpd"
        fake_dhcpd.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake_dhcpd.chmod(0o755)
        fake_systemctl = fake_bin / "systemctl"
        fake_systemctl.write_text("#!/bin/sh\nif [ \"$1\" = is-active ]; then echo active; fi\nexit 0\n", encoding="utf-8")
        fake_systemctl.chmod(0o755)
        self.env = mock.patch.dict(
            os.environ,
            {
                "DHCP_INCLUDES_DIR": str(self.includes),
                "DHCP_SIDECAR_STATE_DIR": str(self.state),
                "DHCPD_BIN": str(fake_dhcpd),
                "SYSTEMCTL_BIN": str(fake_systemctl),
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self._tmpdir.cleanup()

    def test_validate_include_name(self) -> None:
        self.assertEqual(dhcp_ops.validate_include_name("vlan100.conf"), "vlan100.conf")
        with self.assertRaises(dhcp_ops.DhcpSidecarError):
            dhcp_ops.validate_include_name("../evil.conf")
        with self.assertRaises(dhcp_ops.DhcpSidecarError):
            dhcp_ops.validate_include_name("no-extension")

    def test_manifest_reserved_name(self) -> None:
        with self.assertRaises(dhcp_ops.DhcpSidecarError):
            dhcp_ops.validate_include_name(dhcp_ops.INCLUDES_MANIFEST_NAME)

    def test_regenerate_includes_manifest(self) -> None:
        (self.includes / "a.conf").write_text("subnet 10.0.0.0 netmask 255.255.255.0 {}\n")
        manifest = dhcp_ops.regenerate_includes_manifest()
        text = manifest.read_text(encoding="utf-8")
        self.assertIn('include "', text)
        self.assertIn("a.conf", text)
        self.assertEqual(len(dhcp_ops.list_includes()), 1)

    def test_list_and_read(self) -> None:
        (self.includes / "a.conf").write_text("subnet 10.0.0.0 netmask 255.255.255.0 {}\n")
        rows = dhcp_ops.list_includes()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].name, "a.conf")
        body = dhcp_ops.read_include("a.conf")
        self.assertIn("subnet", body["content"])

    @mock.patch("dhcp_ops.subprocess.run")
    def test_validate_runs_dhcpd_t(self, run_mock: mock.MagicMock) -> None:
        run_mock.return_value = mock.Mock(returncode=0, stdout="ok", stderr="")
        out = dhcp_ops.validate_include("vlan1.conf", "subnet 10.1.0.0 netmask 255.255.255.0 {}")
        self.assertTrue(out["validated"])
        self.assertTrue(run_mock.called)
        args = run_mock.call_args[0][0]
        self.assertIn("-t", args)

    @mock.patch("dhcp_ops.reload_service")
    @mock.patch("dhcp_ops.run_dhcpd_test")
    def test_apply_writes_file_and_backups(
        self,
        test_mock: mock.MagicMock,
        reload_mock: mock.MagicMock,
    ) -> None:
        test_mock.return_value = {"ok": True, "returncode": 0}
        reload_mock.return_value = {"is_active": "active"}
        (self.includes / "vlan1.conf").write_text("old\n")
        result = dhcp_ops.apply_include(
            "vlan1.conf",
            "subnet 10.1.0.0 netmask 255.255.255.0 { range 10.1.0.50 10.1.0.200; }",
            change_id="chg-001",
        )
        self.assertTrue(result["applied"])
        self.assertIn("range", (self.includes / "vlan1.conf").read_text())
        manifest = json.loads(
            (self.state / "backups" / "chg-001" / "manifest.json").read_text()
        )
        self.assertTrue(manifest["vlan1.conf"]["existed"])

    @mock.patch("dhcp_ops.reload_service")
    @mock.patch("dhcp_ops.run_dhcpd_test")
    def test_rollback_restores_previous(
        self,
        test_mock: mock.MagicMock,
        reload_mock: mock.MagicMock,
    ) -> None:
        test_mock.return_value = {"ok": True, "returncode": 0}
        reload_mock.return_value = {"is_active": "active"}
        (self.includes / "vlan1.conf").write_text("original\n")
        dhcp_ops.apply_include("vlan1.conf", "updated\n", change_id="chg-002")
        self.assertEqual((self.includes / "vlan1.conf").read_text(), "updated\n")
        dhcp_ops.rollback_change("chg-002")
        self.assertEqual((self.includes / "vlan1.conf").read_text(), "original\n")


if __name__ == "__main__":
    unittest.main()
