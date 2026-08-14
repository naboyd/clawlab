#!/usr/bin/env python3
"""Tests for MCP personal access tokens and identity resolution."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SSH_OPS = REPO / "ssh-ops-mcp"
CLAW_AUTH = REPO / "claw-auth"
sys.path.insert(0, str(SSH_OPS))
sys.path.insert(0, str(CLAW_AUTH))

import mcp_identity
import mcp_tokens
import store


class McpPatTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "users.db"
        os.environ["CLAW_AUTH_DB"] = str(self.db)
        store.DB_PATH = self.db
        store.init_db()
        store.create_user("alice", "secret", "operator")
        store.create_user("bob", "secret", "admin")
        mcp_tokens.ensure_schema()

    def tearDown(self) -> None:
        self._tmp.cleanup()
        os.environ.pop("SSH_OPS_TRUSTED_PROXY_IPS", None)

    def test_valid_pat(self) -> None:
        raw = mcp_tokens.issue_pat("alice", "cursor")
        got = mcp_tokens.validate_pat(raw)
        self.assertEqual(got, {"username": "alice", "role": "operator"})

    def test_wrong_prefix(self) -> None:
        self.assertIsNone(mcp_tokens.validate_pat("not_a_pat_token"))

    def test_revoked_pat(self) -> None:
        raw = mcp_tokens.issue_pat("alice", "x")
        row = mcp_tokens.list_pats("alice")[0]
        mcp_tokens.revoke_pat(row["id"], actor="alice")
        self.assertIsNone(mcp_tokens.validate_pat(raw))

    def test_disabled_user(self) -> None:
        raw = mcp_tokens.issue_pat("alice", "x")
        with store._connect() as conn:
            conn.execute("UPDATE users SET disabled = 1 WHERE username = 'alice'")
        self.assertIsNone(mcp_tokens.validate_pat(raw))

    def test_expired_pat(self) -> None:
        raw = mcp_tokens.issue_pat("alice", "x", ttl_days=1)
        with store._connect() as conn:
            past = (mcp_tokens._now() - timedelta(days=2)).isoformat()
            conn.execute(
                "UPDATE mcp_tokens SET expires_at = ? WHERE username = 'alice'",
                (past,),
            )
        self.assertIsNone(mcp_tokens.validate_pat(raw))


class McpIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "users.db"
        os.environ["CLAW_AUTH_DB"] = str(self.db)
        store.DB_PATH = self.db
        store.init_db()
        store.create_user("alice", "secret", "operator")
        mcp_tokens.ensure_schema()
        self.pat = mcp_tokens.issue_pat("alice", "test")

    def tearDown(self) -> None:
        self._tmp.cleanup()
        os.environ.pop("SSH_OPS_TRUSTED_PROXY_IPS", None)

    def test_pat_beats_spoofed_headers(self) -> None:
        headers = {
            "Authorization": f"Bearer {self.pat}",
            "X-Auth-User": "evil",
            "X-Auth-Role": "admin",
        }
        result = mcp_identity.resolve_identity(headers, peer_ip="203.0.113.1")
        self.assertEqual(result.username, "alice")
        self.assertEqual(result.role, "operator")
        self.assertFalse(result.invalid_token)

    def test_invalid_pat_flag(self) -> None:
        result = mcp_identity.resolve_identity(
            {"Authorization": "Bearer skops_invalidtoken"},
            peer_ip="1.2.3.4",
        )
        self.assertTrue(result.invalid_token)

    def test_spoofed_user_ignored_without_trusted_proxy(self) -> None:
        result = mcp_identity.resolve_identity(
            {"X-Auth-User": "alice", "X-Auth-Role": "admin"},
            peer_ip="203.0.113.1",
        )
        self.assertIsNone(result.username)

    def test_trusted_proxy_honors_x_auth_user(self) -> None:
        os.environ["SSH_OPS_TRUSTED_PROXY_IPS"] = "127.0.0.1"
        result = mcp_identity.resolve_identity(
            {"X-Auth-User": "alice"},
            peer_ip="127.0.0.1",
        )
        self.assertEqual(result.username, "alice")

    def test_spoofed_admin_role_ignored_without_trusted_proxy(self) -> None:
        result = mcp_identity.resolve_identity(
            {"X-Auth-User": "alice", "X-Auth-Role": "admin"},
            peer_ip="10.0.0.5",
        )
        self.assertIsNone(result.username)

    def test_strip_client_identity(self) -> None:
        stripped = mcp_identity.strip_client_identity({
            "Authorization": "Bearer x",
            "X-Auth-User": "alice",
            "Host": "example",
        })
        self.assertNotIn("X-Auth-User", stripped)
        self.assertIn("Authorization", stripped)
        self.assertIn("Host", stripped)


if __name__ == "__main__":
    unittest.main()
