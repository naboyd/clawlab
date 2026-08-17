"""Build approval-gated DHCP include targets for isc-dhcp sidecar apply."""

from __future__ import annotations

import re
from typing import Any

INCLUDE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*\.conf$")
INCLUDES_MANIFEST_NAME = "00-clawlab-includes.conf"


def normalize_include_name(name: str) -> str:
    name = (name or "").strip()
    if name == INCLUDES_MANIFEST_NAME:
        raise ValueError(f"{INCLUDES_MANIFEST_NAME} is reserved for the sidecar manifest")
    if not INCLUDE_NAME_RE.fullmatch(name):
        raise ValueError(
            "spec.include_name must match [a-zA-Z0-9][a-zA-Z0-9._-]*.conf"
        )
    return name


def build_dhcp_include_target(host_name: str, spec: dict[str, Any]) -> dict[str, Any]:
    include_name = normalize_include_name(
        str(spec.get("include_name") or spec.get("name") or "")
    )
    content = spec.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("spec.content is required (non-empty include file body)")

    intent_bits = [f"DHCP include {include_name} on {host_name}"]
    if spec.get("summary"):
        intent_bits.append(str(spec["summary"]).strip())

    return {
        "name": host_name,
        "type": "dhcp_sidecar",
        "include_name": include_name,
        "summary": " — ".join(intent_bits),
        "apply": {"content": content},
        "rollback": {"via_sidecar": True},
        "verify": ["systemctl is-active isc-dhcp-server"],
        "policy_group": "dhcp_include",
        "group_access": "approve",
    }


def public_spec(spec: dict[str, Any]) -> dict[str, Any]:
    out = dict(spec)
    content = out.get("content")
    if isinstance(content, str) and len(content) > 240:
        out["content"] = content[:240] + f"... ({len(content)} bytes total)"
    return out


def format_apply_preview(target: dict[str, Any]) -> str:
    apply = target.get("apply")
    if isinstance(apply, dict):
        content = str(apply.get("content") or "")
        if len(content) > 120:
            content = content[:120] + "..."
        return f"write {target.get('include_name')}: {content!r}"
    if isinstance(apply, list):
        return "; ".join(str(x) for x in apply)
    return str(apply or "")


def format_rollback_preview(target: dict[str, Any]) -> str:
    rollback = target.get("rollback")
    if isinstance(rollback, dict) and rollback.get("via_sidecar"):
        return "sidecar backup restore"
    if isinstance(rollback, list):
        return "; ".join(str(x) for x in rollback)
    return str(rollback or "")
