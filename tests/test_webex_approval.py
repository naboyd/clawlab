#!/usr/bin/env python3
"""Unit tests for Webex four-eyes approval helpers."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "ssh-ops-mcp"))
sys.path.insert(0, str(REPO / "claw-auth"))

import store  # noqa: E402
import webex_approval  # noqa: E402


class WebexApprovalTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "users.db"
        os.environ["CLAW_AUTH_DB"] = str(self.db)
        store.DB_PATH = self.db
        store.init_db()
        store.create_user("alice", "secret", "operator")
        store.create_user("bob", "secret", "admin")
        store.set_webex_email("alice", "alice@example.com")
        store.set_webex_email("bob", "bob@example.com")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_email_lookup(self) -> None:
        from claw_user_lookup import lookup_username_by_webex_email, clear_role_cache

        clear_role_cache()
        self.assertEqual(lookup_username_by_webex_email("bob@example.com"), "bob")
        self.assertIsNone(lookup_username_by_webex_email("unknown@example.com"))

    def test_action_token_roundtrip(self) -> None:
        os.environ["WEBEX_ACTION_SECRET"] = "test-secret"
        token = webex_approval.mint_action_token("chg-20260813-0001", "approve")
        parsed = webex_approval.verify_action_token(token)
        self.assertEqual(parsed, ("chg-20260813-0001", "approve"))

    def test_adaptive_card_has_actions(self) -> None:
        card = webex_approval.build_proposed_card({
            "id": "chg-20260813-0001",
            "created_by": "alice",
            "risk": "medium",
            "intent": "test",
            "targets": [{"name": "C9300-24P", "apply": ["vlan 10"]}],
        })
        titles = [a["title"] for a in card.get("actions", [])]
        self.assertIn("Approve", titles)
        self.assertIn("Reject", titles)


if __name__ == "__main__":
    unittest.main()
