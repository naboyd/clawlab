#!/usr/bin/env python3
"""Sync ios-xe-policy.yaml from generator + fixed always_block header."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "admin-access"))
from generate_ios_xe_allow_groups import ALLOW_GROUPS  # noqa: E402

POLICY_HEADER = """# IOS-XE configuration policy — single source of truth for:
#   • DefenseClaw inspect (always_block → CRITICAL hard-block)
#   • ssh-ops MCP propose_change / ios_config_lines (allow_groups + always_block)
#
# Command taxonomy aligned with Cisco IOS-XE 17.17 Catalyst 9200 Command Reference
# (see docs/ios-xe-command-reference-index.yaml).
#
# Severity model (DefenseClaw):
#   CRITICAL — always_block entries: never reach the device (hard-block chat/tools)
#   HIGH     — optional advisory rules (alert, not block) for risky-but-permitted ops
#   MCP      — per-group access: deny | approve | allow (see allow_groups.access)
#
# Webex: add event type "change" to webhook events to get alerts when approved
# config is applied (see change_notify.py).
"""

GROUP_CATEGORIES = [
    {"id": "vlan", "label": "VLAN (Part XIII, ch. 15)"},
    {"id": "interface", "label": "Interface & Hardware (Part III, ch. 4)"},
    {"id": "spanning_tree", "label": "Spanning Tree (Part VI, ch. 7)"},
    {"id": "ip_addressing", "label": "IP Addressing (Part IV, ch. 5)"},
    {"id": "routing", "label": "Routing (Part IX, ch. 10)"},
    {"id": "security", "label": "Security & AAA (Part X, ch. 11)"},
    {"id": "qos", "label": "QoS (Part VIII, ch. 9)"},
    {"id": "netmgmt", "label": "Network Management (Part VII, ch. 8)"},
    {"id": "system", "label": "System Management (Part XII, ch. 13)"},
    {"id": "multicast", "label": "Multicast (Part V, ch. 6)"},
    {"id": "fabric", "label": "SD-Access / TrustSec / Stacking"},
    {"id": "wireless", "label": "Wireless / WLAN (Catalyst 9800)"},
]

ALWAYS_BLOCK = [
    {
        "id": "IOS-BLK-USERNAME",
        "group": "identity",
        "pattern": r"(?i)^username\s+\S+",
        "title": "Cisco local username create/update",
        "severity": "CRITICAL",
    },
    {
        "id": "IOS-BLK-NO-USERNAME",
        "group": "identity",
        "pattern": r"(?i)^no\s+username\s+\S+",
        "title": "Cisco local username delete",
        "severity": "CRITICAL",
    },
    {
        "id": "IOS-BLK-ENABLE-SECRET",
        "group": "management",
        "pattern": r"(?i)^enable\s+secret\b",
        "title": "Enable secret change",
        "severity": "CRITICAL",
    },
    {
        "id": "IOS-BLK-LINE",
        "group": "management",
        "pattern": r"(?i)^line\s+",
        "title": "Line (console/VTY/AUX) configuration",
        "severity": "CRITICAL",
    },
    {
        "id": "IOS-BLK-IP-SSH",
        "group": "management",
        "pattern": r"(?i)^ip\s+ssh\b",
        "title": "SSH server configuration",
        "severity": "CRITICAL",
    },
    {
        "id": "IOS-BLK-CRYPTO",
        "group": "management",
        "pattern": r"(?i)^crypto\s+",
        "title": "Crypto / PKI / IPsec configuration",
        "severity": "CRITICAL",
    },
    {
        "id": "IOS-BLK-CONTROL-PLANE",
        "group": "management",
        "pattern": r"(?i)^control-plane\b",
        "title": "Control-plane service policy",
        "severity": "CRITICAL",
    },
    {
        "id": "IOS-BLK-RELOAD",
        "group": "destructive",
        "pattern": r"(?i)^reload\b",
        "title": "Device reload",
        "severity": "CRITICAL",
    },
    {
        "id": "IOS-BLK-WRITE-ERASE",
        "group": "destructive",
        "pattern": r"(?i)^write\s+erase\b",
        "title": "Erase startup config",
        "severity": "CRITICAL",
    },
    {
        "id": "IOS-BLK-ERASE",
        "group": "destructive",
        "pattern": r"(?i)^erase\s+",
        "title": "Erase flash/filesystem",
        "severity": "CRITICAL",
    },
    {
        "id": "IOS-BLK-FORMAT",
        "group": "destructive",
        "pattern": r"(?i)^format\s+",
        "title": "Format filesystem",
        "severity": "CRITICAL",
    },
    {
        "id": "IOS-BLK-COPY",
        "group": "destructive",
        "pattern": r"(?i)^copy\s+",
        "title": "Copy files or configs (exfil/injection risk)",
        "severity": "CRITICAL",
    },
    {
        "id": "IOS-BLK-BOOT",
        "group": "destructive",
        "pattern": r"(?i)^boot\s+",
        "title": "Boot system / image path",
        "severity": "CRITICAL",
    },
    {
        "id": "IOS-BLK-ARCHIVE",
        "group": "destructive",
        "pattern": r"(?i)^archive\b",
        "title": "Configuration archive",
        "severity": "CRITICAL",
    },
    {
        "id": "IOS-BLK-FACTORY-RESET",
        "group": "destructive",
        "pattern": r"(?i)^factory-reset\b",
        "title": "Factory reset",
        "severity": "CRITICAL",
    },
    {
        "id": "IOS-BLK-INSTALL",
        "group": "destructive",
        "pattern": r"(?i)^install\s+",
        "title": "Software install / SMU",
        "severity": "CRITICAL",
    },
    {
        "id": "IOS-BLK-LICENSE",
        "group": "destructive",
        "pattern": r"(?i)^license\s+",
        "title": "License manipulation",
        "severity": "CRITICAL",
    },
    {
        "id": "IOS-BLK-SDM",
        "group": "destructive",
        "pattern": r"(?i)^sdm\s+prefer\b",
        "title": "SDM template change (reload required)",
        "severity": "CRITICAL",
    },
    {
        "id": "IOS-BLK-KRON",
        "group": "destructive",
        "pattern": r"(?i)^kron\b",
        "title": "Scheduled EXEC (kron)",
        "severity": "CRITICAL",
    },
    {
        "id": "IOS-BLK-EEM",
        "group": "destructive",
        "pattern": r"(?i)^event\s+manager\b",
        "title": "Embedded Event Manager applet",
        "severity": "CRITICAL",
    },
    {
        "id": "IOS-BLK-SNMP-COMMUNITY",
        "group": "snmp",
        "pattern": r"(?i)^snmp-server\s+community\b",
        "title": "SNMP community string",
        "severity": "CRITICAL",
    },
    {
        "id": "IOS-BLK-SNMP-GROUP",
        "group": "snmp",
        "pattern": r"(?i)^snmp-server\s+group\b",
        "title": "SNMP V3 group",
        "severity": "CRITICAL",
    },
    {
        "id": "IOS-BLK-SNMP-USER",
        "group": "snmp",
        "pattern": r"(?i)^snmp-server\s+user\b",
        "title": "SNMP V3 user",
        "severity": "CRITICAL",
    },
    {
        "id": "IOS-BLK-HTTP-SERVER",
        "group": "management",
        "pattern": r"(?i)^ip\s+http\s+server\b",
        "title": "HTTP server enable",
        "severity": "CRITICAL",
    },
]

APPROVAL_POLICY = {
    "require_proposer_identity": True,
    "forbid_self_approval": True,
    "forbidden_proposers": ["agent", "mcp", "system", "unknown", "gui-operator"],
    "default": {"forbid_self_approval": True},
}


def build_policy() -> dict:
    return {
        "version": 1,
        "platform": "ios-xe",
        "mode": "default_deny",
        "approval_policy": APPROVAL_POLICY,
        "always_block": ALWAYS_BLOCK,
        "group_categories": GROUP_CATEGORIES,
        "allow_groups": ALLOW_GROUPS,
    }


def main() -> int:
    policy = build_policy()
    body = yaml.safe_dump(policy, sort_keys=False, default_flow_style=False)
    text = POLICY_HEADER + body
    targets = [
        REPO / "config-templates" / "ios-xe-policy.yaml",
        REPO / "ssh-ops-mcp" / "ios-xe-policy.yaml",
    ]
    for path in targets:
        path.write_text(text)
        print(f"Wrote {path} ({len(policy['allow_groups'])} allow_groups)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
