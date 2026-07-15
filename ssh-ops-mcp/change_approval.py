"""Four-eyes and proposer-identity rules for change approvals."""

from __future__ import annotations

import os
from typing import Any

import ios_xe_policy

# Generic actors that do not satisfy proposer identity (cannot be approved with four-eyes).
_DEFAULT_FORBIDDEN_PROPOSERS = frozenset({
    "agent",
    "mcp",
    "system",
    "unknown",
    "gui-operator",
})


class ApprovalDenied(Exception):
    """Raised when an approval rule blocks the action."""

    def __init__(self, message: str, *, code: str = "denied") -> None:
        super().__init__(message)
        self.code = code


def _norm(user: str | None) -> str:
    return (user or "").strip().lower()


def _approval_policy() -> dict[str, Any]:
    policy = ios_xe_policy.load_policy()
    raw = policy.get("approval_policy")
    return raw if isinstance(raw, dict) else {}


def _flag(name: str, default: bool = True) -> bool:
    pol = _approval_policy()
    if name in pol:
        return bool(pol[name])
    return default


def forbidden_proposers() -> frozenset[str]:
    pol = _approval_policy()
    extra = pol.get("forbidden_proposers") or []
    names = set(_DEFAULT_FORBIDDEN_PROPOSERS)
    if isinstance(extra, list):
        names.update(_norm(x) for x in extra if str(x).strip())
    return frozenset(names)


def require_proposer_identity() -> bool:
    env = os.environ.get("SSH_OPS_REQUIRE_PROPOSER_IDENTITY", "1").lower()
    if env in ("0", "false", "no", "off"):
        return False
    return _flag("require_proposer_identity", True)


def forbid_self_approval_enabled() -> bool:
    env = os.environ.get("SSH_OPS_FORBID_SELF_APPROVAL", "1").lower()
    if env in ("0", "false", "no", "off"):
        return False
    pol = _approval_policy()
    default = pol.get("default") if isinstance(pol.get("default"), dict) else {}
    if isinstance(default, dict) and "forbid_self_approval" in default:
        return bool(default["forbid_self_approval"])
    return _flag("forbid_self_approval", True)


def validate_proposer(created_by: str) -> None:
    """Reject proposals without a real human/service identity."""
    if not require_proposer_identity():
        return
    actor = (created_by or "").strip()
    if not actor:
        raise ApprovalDenied(
            "Proposer identity is required. Pass requested_by on propose_change "
            "or forward X-Auth-User / X-OpenClaw-User on HTTP MCP.",
            code="missing_proposer",
        )
    if _norm(actor) in forbidden_proposers():
        raise ApprovalDenied(
            f"Proposer identity '{actor}' is not allowed. Pass requested_by with the "
            "real portal username, or configure the gateway to forward X-Auth-User.",
            code="anonymous_proposer",
        )


def is_self_approval(change: dict[str, Any], approver: str) -> bool:
    if not forbid_self_approval_enabled():
        return False
    proposer = _norm(str(change.get("created_by") or ""))
    user = _norm(approver)
    if not proposer or not user:
        return False
    if proposer in forbidden_proposers():
        return False
    return proposer == user


def assert_can_approve(change: dict[str, Any], approver: str) -> None:
    """Raise ApprovalDenied if approver may not approve this change."""
    if change.get("status") != "proposed":
        raise ApprovalDenied(
            f"Change {change.get('id')} is not proposed (status={change.get('status')}).",
            code="wrong_status",
        )
    if is_self_approval(change, approver):
        proposer = change.get("created_by") or "—"
        raise ApprovalDenied(
            f"You cannot approve your own change (four-eyes required). "
            f"Proposed by '{proposer}'; approver is '{approver}'.",
            code="self_approval",
        )


def user_may_approve(change: dict[str, Any], approver: str) -> bool:
    try:
        assert_can_approve(change, approver)
        return True
    except ApprovalDenied:
        return False
