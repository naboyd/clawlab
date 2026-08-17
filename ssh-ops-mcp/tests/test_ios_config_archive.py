"""Tests for IOS config archive / drift detection."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ios_config_archive


SAMPLE_BASE = """\
version 17.9
!
hostname SW1
!
interface Vlan1
 ip address 10.0.0.1 255.255.255.0
!
"""

SAMPLE_CURRENT = """\
version 17.9
!
hostname SW1
!
interface Vlan1
 ip address 10.0.0.2 255.255.255.0
!
"""


class TestNormalizeAndDiff(unittest.TestCase):
    def test_normalize_strips_volatile_lines(self) -> None:
        raw = "! Last configuration change at 10:00:00 UTC\n" + SAMPLE_BASE
        norm = ios_config_archive.normalize_config(raw)
        self.assertNotIn("Last configuration change", norm)
        self.assertIn("hostname SW1", norm)

    def test_meaningful_diff_detected(self) -> None:
        diff = ios_config_archive.unified_diff(SAMPLE_BASE, SAMPLE_CURRENT, host_name="SW1")
        self.assertTrue(ios_config_archive.has_meaningful_diff(diff))
        self.assertIn("10.0.0.2", diff)

    def test_identical_after_normalize_unchanged(self) -> None:
        diff = ios_config_archive.unified_diff(SAMPLE_BASE, SAMPLE_BASE, host_name="SW1")
        self.assertFalse(ios_config_archive.has_meaningful_diff(diff))


class TestInBandCorrelation(unittest.TestCase):
    def test_finds_applied_change_on_host(self) -> None:
        changes = [
            {
                "id": "chg-20260817-0001",
                "status": "applied",
                "change_type": "ios_config_lines",
                "apply_finished_at": "2026-08-17T12:00:00+00:00",
                "targets": [{"name": "SW1"}],
            },
            {
                "id": "chg-20260817-0002",
                "status": "applied",
                "change_type": "ios_config_lines",
                "apply_finished_at": "2026-08-16T12:00:00+00:00",
                "targets": [{"name": "SW1"}],
            },
        ]
        with patch.object(ios_config_archive.change_store, "list_changes", return_value=changes):
            matched = ios_config_archive.find_in_band_changes(
                "SW1",
                since_iso="2026-08-17T10:00:00+00:00",
            )
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["id"], "chg-20260817-0001")


class TestDriftWorkflow(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.archive = Path(self._tmp.name) / "archive"
        os.environ["SSH_OPS_IOS_ARCHIVE_DIR"] = str(self.archive)

    def test_initial_baseline_no_drift(self) -> None:
        with patch.object(ios_config_archive, "fetch_running_config", return_value=SAMPLE_BASE):
            result = ios_config_archive.check_host_drift("SW1", notify=False)
        self.assertEqual(result["status"], "baseline_initialized")
        self.assertTrue(ios_config_archive.baseline_path("SW1").is_file())

    def test_oob_drift_archives_artifacts(self) -> None:
        ios_config_archive.set_baseline("SW1", SAMPLE_BASE, reason="test")
        meta = ios_config_archive.meta_path("SW1")
        meta.write_text(json.dumps({"baseline_updated_at": "2026-08-17T08:00:00+00:00"}))

        with patch.object(ios_config_archive, "fetch_running_config", return_value=SAMPLE_CURRENT):
            with patch.object(ios_config_archive.change_store, "list_changes", return_value=[]):
                with patch.object(ios_config_archive.change_notify, "notify_ios_config_oob_drift") as notify:
                    notify.return_value = {"notified": True}
                    result = ios_config_archive.check_host_drift("SW1", notify=True)

        self.assertEqual(result["status"], "out_of_band")
        self.assertTrue(result["drift"])
        diff_path = Path(result["artifacts"]["diff"])
        new_path = Path(result["artifacts"]["new_config"])
        self.assertTrue(diff_path.is_file())
        self.assertTrue(new_path.is_file())
        notify.assert_called_once()


if __name__ == "__main__":
    unittest.main()
