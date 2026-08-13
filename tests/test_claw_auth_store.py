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
        store.create_user("admin", "secret", "admin")
        store.create_user("alice", "secret", "operator")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_update_user_role_and_webex(self) -> None:
        store.update_user("alice", role="admin", webex_email="alice@example.com")
        user = store.get_user("alice")
        assert user is not None
        self.assertEqual(user["role"], "admin")
        self.assertEqual(user["webex_email"], "alice@example.com")

    def test_cannot_demote_last_admin(self) -> None:
        with self.assertRaises(ValueError):
            store.update_user("admin", role="operator", actor="admin")

    def test_cannot_disable_self(self) -> None:
        with self.assertRaises(ValueError):
            store.update_user("admin", disabled=True, actor="admin")


if __name__ == "__main__":
    unittest.main()
