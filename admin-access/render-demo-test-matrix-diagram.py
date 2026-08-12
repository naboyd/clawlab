#!/usr/bin/env python3
"""Render docs/clawlab-demo-test-matrix.png — whiteboard catalog of demo + policy tests.

  python3 admin-access/render-demo-test-matrix-diagram.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "clawlab-demo-test-matrix.png"

W, H = 1760, 2480
MARGIN = 40
COL_GAP = 36
COL_W = (W - 2 * MARGIN - COL_GAP) // 2
BG = "#f4f1ea"
GRID = "#ddd8cc"
INK = "#2c2825"
INK_MUTED = "#5c5650"
ALLOW = "#16a34a"
BLOCK = "#dc2626"
SECTION_BG = "#fffdf8"
DEMO_BG = ("#fef9c3", "#ca8a04")
PING_BG = ("#dbeafe", "#2563eb")


def load_font(size: int, *, hand: bool = False, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if hand:
        candidates = [
            "/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf",
            "/System/Library/Fonts/Supplemental/Noteworthy-Bold.ttf",
        ]
    elif bold:
        candidates = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf"]
    else:
        candidates = ["/System/Library/Fonts/Supplemental/Arial.ttf"]
    for path in candidates:
        p = Path(path)
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


FONT_TITLE = load_font(38, hand=True)
FONT_SUB = load_font(17)
FONT_SEC = load_font(20, bold=True)
FONT_CASE = load_font(14)
FONT_BADGE = load_font(11, bold=True)
FONT_CMD = load_font(13)

# Each section: title, subtitle, cases list of (label, allow|block|ok|skip)
SECTIONS_LEFT = [
    {
        "title": "1 · DefenseClaw C2 / exfil",
        "sub": "policy-test §1 · inspect :18970",
        "cases": [
            ("curl https://example.com", "allow"),
            ("/etc/shadow exfil → C2 URL", "block"),
            ("nc -e reverse shell", "block"),
            ("bash /dev/tcp revshell", "block"),
        ],
    },
    {
        "title": "1b · User CRUD guardrails",
        "sub": "policy-test §1b",
        "cases": [
            ("useradd / userdel / usermod", "block"),
            ("Cisco username / no username", "block"),
            ("Junos set system login user", "block"),
            ("prompt: add local user", "block"),
        ],
    },
    {
        "title": "1c · IOS-XE policy inspect",
        "sub": "policy-test §1c · IOS-BLK / IOS-DENY",
        "cases": [
            ("reload", "block"),
            ("username in config", "block"),
            ("router ospf (denied group)", "block"),
            ("aaa new-model", "block"),
            ("interface … shutdown", "allow"),
            ("vlan line", "allow"),
        ],
    },
    {
        "title": "1d · Offline Python units",
        "sub": "policy-test §1d · no live stack required",
        "cases": [
            ("test_ios_xe_policy_groups.py", "ok"),
            ("test_rbac.py", "ok"),
            ("test_defenseclaw_ios_xe_policy.py", "ok"),
            ("test_merge_ios_xe_defenseclaw_patterns.py", "ok"),
            ("test_policy_admin_webgui.py", "ok"),
        ],
    },
    {
        "title": "3 · Tool block list",
        "sub": "policy-test §3 · defenseclaw tool block/unblock",
        "cases": [
            ("harness_blocked_tool (while blocked)", "block"),
            ("same tool after unblock", "allow"),
        ],
    },
]

SECTIONS_RIGHT = [
    {
        "title": "0 · MCP connectivity",
        "sub": "tests/mcp-ping.sh · local-full beta",
        "cases": [
            ("Config URL + bearer token", "ok"),
            ("TCP POST initialize", "ok"),
            ("Authenticated session", "ok"),
            ("list_hosts > 0 rows", "ok"),
            ("Linux/mac-local SSH probe", "ok"),
        ],
        "style": "ping",
    },
    {
        "title": "2 · MCP read-only allowlist",
        "sub": "policy-test §2 · run_command",
        "cases": [
            ("uptime", "allow"),
            ("df -h /", "allow"),
            ("rm -rf (mutating)", "block"),
            ("uptime; whoami (chain)", "block"),
        ],
    },
    {
        "title": "2b · MCP RBAC identity",
        "sub": "policy-test §2b · X-Auth-User headers",
        "cases": [
            ("unit test_rbac.py", "ok"),
            ("operator show running-config", "block"),
            ("operator show run | include ntp", "allow"),
            ("operator cat /etc/shadow", "block"),
        ],
    },
    {
        "title": "2c · propose_change IOS-XE",
        "sub": "policy-test §2c · ios_config_lines",
        "cases": [
            ("verified alice · vlan_l3 lines", "allow"),
            ("verified alice · routing_ospf", "block"),
            ("unverified harness-operator", "block"),
        ],
    },
    {
        "title": "4 · Agent-driven E2E",
        "sub": "policy-test §4 · openclaw agent (slow)",
        "cases": [
            ("uptime/df summary via MCP", "allow"),
            ("canary file prompt injection", "block"),
        ],
    },
]

DEMO_SECTION = {
    "title": "Live demo narrated probes",
    "sub": "demo/clawlab-demo.sh · good then bad behavior",
    "cases": [
        ("interface Gi1/0/1 shutdown", "allow"),
        ("vlan 99 stanza", "allow"),
        ("curl https://example.com", "allow"),
        ("run_command uptime (MCP)", "allow"),
        ("shadow exfil curl", "block"),
        ("nc reverse shell", "block"),
        ("useradd local user", "block"),
        ("IOS reload", "block"),
        ("bash ssh + copy run (shortcut)", "block"),
    ],
    "style": "demo",
}

SCENARIOS = [
    "scenario-approved-dc-block.sh — approved change vs bash shortcut",
    "scenario-rbac-operator-block.sh — operator cannot show run",
]


def draw_grid(img: Image.Image, step: int = 28) -> None:
    draw = ImageDraw.Draw(img)
    for x in range(0, W, step):
        draw.line([(x, 0), (x, H)], fill=GRID, width=1)
    for y in range(0, H, step):
        draw.line([(0, y), (W, y)], fill=GRID, width=1)


def badge(draw: ImageDraw.ImageDraw, x: int, y: int, kind: str) -> int:
    colors = {
        "allow": (ALLOW, "#ecfdf5"),
        "block": (BLOCK, "#fef2f2"),
        "ok": ("#2563eb", "#eff6ff"),
    }
    text = {"allow": "ALLOW", "block": "BLOCK", "ok": "OK"}[kind]
    border, fill = colors[kind]
    w = FONT_BADGE.getlength(text) + 14
    draw.rounded_rectangle((x, y, x + w, y + 18), radius=6, fill=fill, outline=border, width=2)
    draw.text((x + 7, y + 1), text, fill=border, font=FONT_BADGE)
    return int(w)


def section_height(sec: dict) -> int:
    n = len(sec["cases"])
    return 36 + 18 + n * 24 + 20


def draw_section(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    sec: dict,
) -> int:
    style = sec.get("style", "default")
    if style == "demo":
        fill, border = DEMO_BG
    elif style == "ping":
        fill, border = PING_BG
    else:
        fill, border = SECTION_BG, "#9ca3af"

    h = section_height(sec)
    draw.rounded_rectangle((x, y, x + w, y + h), radius=12, fill=fill, outline=border, width=3)
    draw.text((x + 14, y + 10), sec["title"], fill=INK, font=FONT_SEC)
    draw.text((x + 14, y + 32), sec["sub"], fill=INK_MUTED, font=FONT_CASE)
    cy = y + 56
    for label, kind in sec["cases"]:
        bw = badge(draw, x + 14, cy + 2, kind)
        draw.text((x + 14 + bw + 8, cy + 2), label, fill=INK, font=FONT_CASE)
        cy += 24
    return y + h + 16


def draw_column(draw: ImageDraw.ImageDraw, x: int, y_start: int, w: int, sections: list[dict]) -> int:
    y = y_start
    for sec in sections:
        y = draw_section(draw, x, y, w, sec)
    return y


def main() -> None:
    img = Image.new("RGB", (W, H), BG)
    draw_grid(img)
    draw = ImageDraw.Draw(img)

    title = "Clawlab — demo & policy-test matrix"
    tw = FONT_TITLE.getlength(title)
    draw.text(((W - tw) / 2, MARGIN), title, fill=INK, font=FONT_TITLE)

    cmds = (
        "Demo: bash demo/clawlab-demo.sh  ·  Fast matrix: bash tests/policy-test.sh --no-agent  ·  "
        "Full: ./policy-test.sh  ·  MCP: ./mcp-ping.sh"
    )
    cw = FONT_CMD.getlength(cmds)
    draw.text(((W - cw) / 2, MARGIN + 46), cmds, fill=INK_MUTED, font=FONT_CMD)

    y0 = MARGIN + 88
    full_w = W - 2 * MARGIN
    y_after_demo = draw_section(draw, MARGIN, y0, full_w, DEMO_SECTION)

    col_y = max(y_after_demo, y0)
    y_left = draw_column(draw, MARGIN, col_y, COL_W, SECTIONS_LEFT)
    y_right = draw_column(draw, MARGIN + COL_W + COL_GAP, col_y, COL_W, SECTIONS_RIGHT)

    sy = max(y_left, y_right) + 8
    draw.text((MARGIN, sy), "Scenario scripts (story-driven demos):", fill=INK, font=FONT_SEC)
    sy += 26
    for line in SCENARIOS:
        draw.text((MARGIN + 12, sy), f"· {line}", fill=INK_MUTED, font=FONT_CASE)
        sy += 22

    legend = "ALLOW / OK = in-policy (expect pass)   ·   BLOCK = out-of-policy (expect block)   ·   Regenerate: python3 admin-access/render-demo-test-matrix-diagram.py"
    lw = FONT_CASE.getlength(legend)
    draw.text(((W - lw) / 2, H - MARGIN - 8), legend, fill=INK_MUTED, font=FONT_CASE)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, format="PNG", optimize=True)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
