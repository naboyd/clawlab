#!/usr/bin/env python3
"""Policy tab admin RBAC and reload helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ssh-ops-mcp"))

import rbac  # noqa: E402


class PolicyAdminRbacTests(unittest.TestCase):
    @patch.object(rbac, "rbac_enabled", return_value=True)
    def test_operator_denied(self, _enabled) -> None:
        with self.assertRaises(rbac.RbacDenied):
            rbac.check_policy_admin(
                role="operator", username="alice", action="Policy group edits"
            )

    @patch.object(rbac, "rbac_enabled", return_value=True)
    def test_admin_allowed(self, _enabled) -> None:
        rbac.check_policy_admin(
            role="admin", username="admin", action="Policy enforcement reload"
        )


class PolicyReloadApiTests(unittest.TestCase):
    @patch.dict(
        "os.environ",
        {"CLAWLAB_INTERNAL_TOKEN": "test-token", "DEFENSECLAW_POLICY_RELOAD_URL": ""},
        clear=False,
    )
    @patch("policy_reload.urllib.request.urlopen")
    def test_calls_defenseclaw_api(self, mock_urlopen) -> None:
        import policy_reload

        class Resp:
            def read(self):
                return b'{"ok": true, "message": "merged"}'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        mock_urlopen.return_value = Resp()
        ok, msg = policy_reload._call_defenseclaw_api(reload_openclaw=False)
        self.assertTrue(ok)
        self.assertIn("merged", msg)


if __name__ == "__main__":
    unittest.main()
