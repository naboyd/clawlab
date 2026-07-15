#!/usr/bin/env python3
"""Unit tests for ssh-ops RBAC and actor resolution."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "ssh-ops-mcp"
sys.path.insert(0, str(ROOT))

import change_actor
import rbac


class RbacPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["SSH_OPS_RBAC"] = "1"

    def test_admin_allows_full_config(self) -> None:
        rbac.check_run_command(
            role="admin",
            command="show running-config",
            platform="cisco_ios",
        )

    def test_operator_blocks_full_config(self) -> None:
        with self.assertRaises(rbac.RbacDenied) as ctx:
            rbac.check_run_command(
                role="operator",
                command="show running-config",
                platform="cisco_ios",
            )
        self.assertEqual(ctx.exception.code, "sensitive_read")

    def test_operator_allows_filtered_show(self) -> None:
        rbac.check_run_command(
            role="operator",
            command="show run | include interface",
            platform="cisco_ios",
        )

    def test_operator_blocks_download(self) -> None:
        with self.assertRaises(rbac.RbacDenied):
            rbac.check_download_file(role="operator")

    def test_trusted_header_wins_over_requested_by(self) -> None:
        change_actor.set_request_identity("alice", "operator")
        actor = change_actor.resolve_actor()
        self.assertEqual(actor, "alice")

    def test_requested_by_mismatch_raises(self) -> None:
        change_actor.set_request_identity("alice", "operator")
        with self.assertRaises(change_actor.IdentityMismatch):
            change_actor.resolve_actor("bob")


class RbacDbTests(unittest.TestCase):
    def test_lookup_role_from_sqlite(self) -> None:
        import sqlite3

        from claw_user_lookup import clear_role_cache, lookup_role

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "users.db"
            conn = sqlite3.connect(db)
            conn.execute(
                "CREATE TABLE users (username TEXT PRIMARY KEY, role TEXT, disabled INT)"
            )
            conn.execute(
                "INSERT INTO users VALUES ('alice', 'operator', 0)"
            )
            conn.commit()
            conn.close()

            os.environ["CLAW_AUTH_DB"] = str(db)
            clear_role_cache()
            self.assertEqual(lookup_role("alice"), "operator")


if __name__ == "__main__":
    unittest.main()
