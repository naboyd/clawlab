#!/usr/bin/env python3
"""Tests for change-engine verify handling."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ssh-ops-mcp"))

# Allow imports without full container deps (secrets_store → cryptography).
try:
    import cryptography  # noqa: F401
except ModuleNotFoundError:
    import types

    _crypto = types.ModuleType("cryptography")
    _fernet = types.ModuleType("cryptography.fernet")

    class _StubFernet:  # noqa: D106
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            pass

    _fernet.Fernet = _StubFernet
    _fernet.InvalidToken = Exception
    sys.modules["cryptography"] = _crypto
    sys.modules["cryptography.fernet"] = _fernet

import change_policy
import ios_change
import network_apply
import verify_spec


INCIDENT_VERIFY = {
    "command": "show running-config | include helper-address 192.168.128.16",
    "expect_contains": "192.168.128.16",
}


class VerifySpecTests(unittest.TestCase):
    def test_reject_bare_verify_dict(self) -> None:
        _entries, errors = verify_spec.parse_verify_input(INCIDENT_VERIFY)
        self.assertTrue(errors)
        self.assertIn("bare object", errors[0].lower())

    def test_accept_structured_list(self) -> None:
        entries, errors = verify_spec.parse_verify_input([INCIDENT_VERIFY])
        self.assertFalse(errors)
        self.assertEqual(entries[0]["command"], INCIDENT_VERIFY["command"])

    def test_accept_string_list(self) -> None:
        entries, errors = verify_spec.parse_verify_input(
            ["show running-config | include helper-address"]
        )
        self.assertFalse(errors)
        self.assertEqual(entries, ["show running-config | include helper-address"])

    def test_invert_structured_entry(self) -> None:
        inv = verify_spec.invert_verify_entry(
            {"command": "show run | include foo", "expect_contains": "foo"}
        )
        self.assertEqual(inv["expect_not_contains"], "foo")


class ChangePolicyVerifyTests(unittest.TestCase):
    def test_incident_spec_rejected_at_proposal(self) -> None:
        spec = {
            "lines": ["interface Vlan100", " ip helper-address 192.168.128.16"],
            "group": "ip_helpers",
            "verify": INCIDENT_VERIFY,
        }
        risk, errors, _warnings = change_policy.validate_proposal(
            "ios_config_lines",
            spec,
            platform="cisco_ios",
        )
        self.assertTrue(errors)
        self.assertEqual(risk, "blocked")

    def test_config_absent_verify_expect(self) -> None:
        expect, errors = verify_spec.parse_verify_expect("config_absent")
        self.assertFalse(errors)
        self.assertEqual(expect, "config_absent")


class NetworkApplyVerifyTests(unittest.TestCase):
    @patch.object(network_apply, "run_show")
    def test_plain_string_list_unchanged(self, mock_show) -> None:
        mock_show.return_value = "helper-address 10.0.0.1"
        ok, results = network_apply.verify_target(
            {
                "name": "sw1",
                "verify": ["show run | include helper-address"],
                "verify_expect": "config_present",
            }
        )
        self.assertTrue(ok)
        self.assertEqual(results[0]["command"], "show run | include helper-address")

    @patch.object(network_apply, "run_show")
    def test_expect_not_contains_passes_on_removal(self, mock_show) -> None:
        mock_show.return_value = ""
        ok, results = network_apply.verify_target(
            {
                "name": "sw1",
                "verify": [
                    {
                        "command": "show run | include helper-address 10.0.0.1",
                        "expect_not_contains": "10.0.0.1",
                    }
                ],
            }
        )
        self.assertTrue(ok)
        self.assertIn("expect_not_contains", results[0]["expectation"])

    @patch.object(network_apply, "run_show")
    def test_expect_not_contains_fails_when_text_remains(self, mock_show) -> None:
        mock_show.return_value = " ip helper-address 10.0.0.1"
        ok, _results = network_apply.verify_target(
            {
                "name": "sw1",
                "verify": [
                    {
                        "command": "show run | include helper-address",
                        "expect_not_contains": "10.0.0.1",
                    }
                ],
            }
        )
        self.assertFalse(ok)

    @patch.object(network_apply, "run_show")
    def test_expect_empty_passes(self, mock_show) -> None:
        mock_show.return_value = ""
        ok, _results = network_apply.verify_target(
            {
                "name": "sw1",
                "verify": [{"command": "show run | include foo", "expect_empty": True}],
            }
        )
        self.assertTrue(ok)

    @patch.object(network_apply, "run_show")
    def test_invalid_input_always_fails(self, mock_show) -> None:
        mock_show.return_value = "% Invalid input detected at '^' marker."
        ok, _results = network_apply.verify_target(
            {
                "name": "sw1",
                "verify": [{"command": "command", "expect_contains": "x"}],
            }
        )
        self.assertFalse(ok)

    @patch.object(network_apply, "run_show")
    def test_config_absent_passes_on_empty_output(self, mock_show) -> None:
        mock_show.return_value = ""
        ok, _results = network_apply.verify_target(
            {
                "name": "sw1",
                "verify": ["show run | include helper-address 10.0.0.1"],
                "verify_expect": "config_absent",
            }
        )
        self.assertTrue(ok)


class ChangeEngineApplyTests(unittest.TestCase):
    def setUp(self) -> None:
        import change_engine
        import change_store

        self.change_engine = change_engine
        self.change_store = change_store
        self._tmp = Path(__file__).resolve().parent / "_tmp_changes"
        self._tmp.mkdir(exist_ok=True)
        self.change_store.CHANGES_DIR = self._tmp
        for path in self._tmp.glob("*.yaml"):
            path.unlink()

    def tearDown(self) -> None:
        for path in self._tmp.glob("*.yaml"):
            path.unlink()

    def _approved_change(self, target: dict) -> str:
        cid = self.change_store.next_id()
        self.change_store.save(
            {
                "id": cid,
                "status": "approved",
                "change_type": "ios_config_lines",
                "spec": {"lines": target.get("apply", [])},
                "targets": [target],
            }
        )
        return cid

    @patch.object(network_apply, "write_memory", return_value="ok")
    @patch.object(network_apply, "apply_config_lines", return_value=["ok"])
    @patch.object(network_apply, "backup_running_config", return_value=Path("/tmp/bak"))
    @patch.object(network_apply, "verify_target")
    def test_failure_stage_verify_when_apply_ok(
        self,
        mock_verify,
        _bak,
        _apply,
        _save,
    ) -> None:
        mock_verify.return_value = (False, [{"command": "show run", "passed": "False"}])
        cid = self._approved_change(
            {
                "name": "sw1",
                "apply": ["interface Vlan1"],
                "rollback": ["no interface Vlan1"],
                "verify": ["show run"],
                "verify_expect": "config_present",
            }
        )
        result = self.change_engine.apply_change(cid, actor="tester")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure_stage"], "verify")
        stored = self.change_store.load(cid)
        self.assertEqual(stored.get("failure_stage"), "verify")


class BuildTargetTests(unittest.TestCase):
    def test_build_target_accepts_structured_verify(self) -> None:
        target = ios_change.build_ios_config_lines_target(
            "sw1",
            "cisco_ios",
            {
                "lines": ["interface Vlan1", " ip helper-address 10.0.0.2"],
                "group": "ip_helpers",
                "verify": [
                    {
                        "command": "show run | include helper-address 10.0.0.2",
                        "expect_contains": "10.0.0.2",
                    }
                ],
                "verify_expect": "config_present",
            },
        )
        self.assertEqual(len(target["verify"]), 1)
        self.assertIsInstance(target["verify"][0], dict)


if __name__ == "__main__":
    unittest.main()
