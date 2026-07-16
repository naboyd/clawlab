"""Role-based access control for ssh-ops MCP tools."""

from __future__ import annotations

import os
import re

ADMIN_ROLE = "admin"

# Unfiltered full config dumps (operators may use "| include/section/begin").
_FULL_CONFIG_RE = re.compile(
    r"(?i)^show\s+(?:running(?:-config)?|run(?:ning)?(?:-config)?)\s*$"
)
# Abbreviated full dump without a filter pipe.
_FULL_CONFIG_SHORT_RE = re.compile(
    r"(?i)^show\s+run\s*$"
)

_LINUX_SENSITIVE_RE = re.compile(
    r"(?i)(?:^|/)(?:etc/shadow|etc/gshadow|root/|\.ssh/id_|id_rsa|\.pem|credentials)"
)


class RbacDenied(PermissionError):
    def __init__(self, message: str, *, code: str = "rbac_denied") -> None:
        super().__init__(message)
        self.code = code


def rbac_enabled() -> bool:
    env = os.environ.get("SSH_OPS_RBAC", "auto").lower()
    if env in ("0", "false", "no", "off"):
        return False
    if env in ("1", "true", "yes", "on"):
        return True
    # auto: on when claw-auth DB is mounted/readable
    from claw_user_lookup import _db_path

    return _db_path().is_file()


def _norm_role(role: str | None) -> str:
    return (role or "").strip().lower() or "anonymous"


def is_admin(role: str | None) -> bool:
    return _norm_role(role) == ADMIN_ROLE


def effective_role(role: str | None, username: str | None) -> str:
    """Resolve role; unknown authenticated users default to operator."""
    r = _norm_role(role)
    if r != "anonymous":
        return r
    if (username or "").strip():
        return "operator"
    return "anonymous"


def _require_admin(role: str, action: str) -> None:
    if not is_admin(role):
        raise RbacDenied(
            f"{action} requires role '{ADMIN_ROLE}' (you are '{role}').",
            code="admin_required",
        )


def is_sensitive_network_command(command: str) -> bool:
    cmd = (command or "").strip()
    if not cmd:
        return False
    if "|" in cmd:
        return False
    return bool(_FULL_CONFIG_RE.match(cmd) or _FULL_CONFIG_SHORT_RE.match(cmd))


def is_sensitive_linux_command(command: str) -> bool:
    cmd = (command or "").strip()
    if not cmd:
        return False
    return bool(_LINUX_SENSITIVE_RE.search(cmd))


def check_run_command(*, role: str, command: str, platform: str) -> None:
    if not rbac_enabled():
        return
    role = effective_role(role, None)
    if is_admin(role):
        return
    if platform not in ("linux", "unix", ""):
        if is_sensitive_network_command(command):
            raise RbacDenied(
                "Full running-config requires admin role. "
                "Use a filtered show command (e.g. show run | section interface).",
                code="sensitive_read",
            )
        return
    if is_sensitive_linux_command(command):
        raise RbacDenied(
            "Reading sensitive paths requires admin role.",
            code="sensitive_read",
        )


def check_download_file(*, role: str) -> None:
    if not rbac_enabled():
        return
    _require_admin(effective_role(role, None), "download_file")


def check_run_write_command(*, role: str) -> None:
    if not rbac_enabled():
        return
    _require_admin(effective_role(role, None), "run_write_command")


def check_upload_file(*, role: str) -> None:
    if not rbac_enabled():
        return
    _require_admin(effective_role(role, None), "upload_file")


def check_propose_change(*, role: str, username: str | None) -> None:
    if not rbac_enabled():
        return
    role = effective_role(role, username)
    if role == "anonymous":
        raise RbacDenied(
            "Proposer identity is required. Sign in via the portal or send a "
            "verified X-Auth-User / X-Claw-Mcp-Bind header.",
            code="missing_identity",
        )


def check_policy_admin(*, role: str, username: str | None, action: str) -> None:
    """IOS-XE policy edits and enforcement reload require admin role."""
    if not rbac_enabled():
        return
    _require_admin(effective_role(role, username), action)
