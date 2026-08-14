#!/usr/bin/env python3
"""Unit tests for claw-auth user store."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "claw-auth"))

import store  # noqa: E402


class ClawAuthStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "users.db"
        os.environ["CLAW_AUTH_DB"] = str(self.db)
        store.DB_PATH = self.db
        store.init_db()
        store.create_user("root", "secret", "superadmin")
        store.create_user("alice", "secret", "operator")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_roles_include_superadmin(self) -> None:
        self.assertIn("superadmin", store.VALID_ROLES)
        store.create_user("bob", "secret", "admin")
        self.assertEqual(store.get_user("bob")["role"], "admin")

    def test_migrate_admin_user_to_superadmin(self) -> None:
        store.create_user("admin", "secret", "admin")
        store.init_db()
        self.assertEqual(store.get_user("admin")["role"], "superadmin")

    def test_update_user_role_and_webex(self) -> None:
        store.update_user("alice", role="admin", webex_email="alice@example.com")
        user = store.get_user("alice")
        assert user is not None
        self.assertEqual(user["role"], "admin")
        self.assertEqual(user["webex_email"], "alice@example.com")

    def test_cannot_demote_last_superadmin(self) -> None:
        with self.assertRaises(ValueError):
            store.update_user("root", role="admin", actor="root")

    def test_cannot_disable_self(self) -> None:
        with self.assertRaises(ValueError):
            store.update_user("root", disabled=True, actor="root")


if __name__ == "__main__":
    unittest.main()
