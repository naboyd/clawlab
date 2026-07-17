#!/usr/bin/env python3
"""Render docs/clawlab-policy-enforcement-flow.png (4-column dark layout).

Source of truth for layout edits. Mermaid source (.mmd) is kept in sync for
documentation; this script produces the committed PNG when mermaid-cli is unavailable.

Usage:
  python3 admin-access/render-policy-flow-diagram.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "clawlab-policy-enforcement-flow.png"

W, H = 2600, 1500
BG = "#0f1419"
MARGIN = 40
TITLE_H = 72
LEGEND_H = 88
COL_GAP = 36
COL_W = (W - 2 * MARGIN - 3 * COL_GAP) // 4
COL_TOP = MARGIN + TITLE_H + 24
COL_BOTTOM = H - MARGIN - LEGEND_H - 16
COL_H = COL_BOTTOM - COL_TOP

COLORS = {
    "entry_bg": "#1a4a7a",
    "entry_border": "#3498db",
    "dc_bg": "#5c3a0a",
    "dc_border": "#e67e22",
    "crit_bg": "#5c1a1a",
    "crit_border": "#e74c3c",
    "warn_bg": "#4a4020",
    "warn_border": "#f1c40f",
    "mcp_bg": "#1a4030",
    "mcp_border": "#27ae60",
    "mcp_orange_bg": "#5c3a0a",
    "mcp_orange_border": "#e67e22",
    "notify_bg": "#3d2a5c",
    "notify_border": "#9b59b6",
    "text": "#ecf0f1",
    "muted": "#c9d1d9",
    "arrow": "#7f8c8d",
}


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        p = Path(path)
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


FONT_TITLE = load_font(34, bold=True)
FONT_COL = load_font(22, bold=True)
FONT_BOX = load_font(19)
FONT_BOX_SM = load_font(17)
FONT_LEG = load_font(18)


def col_x(index: int) -> int:
    return MARGIN + index * (COL_W + COL_GAP)


def wrap_text(text: str, max_chars: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            trial = f"{current} {word}"
            if len(trial) <= max_chars:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def draw_box(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int, int, int],
    text: str,
    fill: str,
    border: str,
    *,
    dashed: bool = False,
    font: ImageFont.ImageFont = FONT_BOX,
) -> None:
    x1, y1, x2, y2 = xy
    if dashed:
        draw.rounded_rectangle(xy, radius=12, outline=border, width=3)
        for i in range(x1, x2, 14):
            draw.line([(i, y1), (min(i + 8, x2), y1)], fill=border, width=3)
            draw.line([(i, y2), (min(i + 8, x2), y2)], fill=border, width=3)
        for i in range(y1, y2, 14):
            draw.line([(x1, i), (x1, min(i + 8, y2))], fill=border, width=3)
            draw.line([(x2, i), (x2, min(i + 8, y2))], fill=border, width=3)
    else:
        draw.rounded_rectangle(xy, radius=12, fill=fill, outline=border, width=3)

    lines = wrap_text(text, max(18, (x2 - x1) // 11))
    line_h = font.size + 6
    total_h = len(lines) * line_h
    ty = y1 + max(8, (y2 - y1 - total_h) // 2)
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        tw = bbox[2] - bbox[0]
        draw.text(((x1 + x2 - tw) // 2, ty), line, fill=COLORS["text"], font=font)
        ty += line_h


def draw_column(
    draw: ImageDraw.ImageDraw,
    index: int,
    title: str,
    boxes: list[tuple[str, str, str, bool]],
) -> None:
    x = col_x(index)
    draw.rounded_rectangle(
        (x, COL_TOP, x + COL_W, COL_BOTTOM),
        radius=16,
        outline="#30363d",
        width=2,
    )
    tb = draw.textbbox((0, 0), title, font=FONT_COL)
    tw = tb[2] - tb[0]
    draw.text((x + (COL_W - tw) // 2, COL_TOP - 34), title, fill=COLORS["muted"], font=FONT_COL)

    n = len(boxes)
    gap = 14
    box_h = (COL_H - gap * (n + 1)) // n
    y = COL_TOP + gap
    for text, fill, border, dashed in boxes:
        draw_box(draw, (x + 14, y, x + COL_W - 14, y + box_h), text, fill, border, dashed=dashed)
        y += box_h + gap


def draw_arrow(draw: ImageDraw.ImageDraw, x1: int, x2: int, y: int) -> None:
    draw.line([(x1, y), (x2, y)], fill=COLORS["arrow"], width=4)
    draw.polygon([(x2, y), (x2 - 16, y - 10), (x2 - 16, y + 10)], fill=COLORS["arrow"])


def main() -> None:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    title = "Clawlab — Policy Enforcement Flow (2026)"
    tb = draw.textbbox((0, 0), title, font=FONT_TITLE)
    draw.text(((W - (tb[2] - tb[0])) // 2, MARGIN), title, fill=COLORS["text"], font=FONT_TITLE)

    draw_column(
        draw,
        0,
        "1 · USER ENTRY POINTS",
        [
            ("Operator", COLORS["entry_bg"], COLORS["entry_border"], False),
            ("OpenClaw Chat\nControl UI · /openclaw/", COLORS["entry_bg"], COLORS["entry_border"], False),
            ("claw-auth login\nunified portal :8443", COLORS["entry_bg"], COLORS["entry_border"], False),
            (
                "MCP Admin Portal · /ssh-ops/\nHosts · Discovery · Changes · Policy",
                COLORS["entry_bg"],
                COLORS["entry_border"],
                False,
            ),
        ],
    )

    draw_column(
        draw,
        1,
        "2 · DEFENSECLAW — Inspect & Block",
        [
            (
                "Prompt / Chat Inspect\nregex + LLM judge\nFoundation-Sec or Cisco AI Defense",
                COLORS["dc_bg"],
                COLORS["dc_border"],
                False,
            ),
            ("CRITICAL = hard block", COLORS["crit_bg"], COLORS["crit_border"], False),
            (
                "Tool Inspect API :18970\nexec shims · bash · curl · nc",
                COLORS["dc_bg"],
                COLORS["dc_border"],
                False,
            ),
            ("CRITICAL patterns · IOS-BLK / IOS-DENY", COLORS["crit_bg"], COLORS["crit_border"], False),
            ("HIGH Advisory Alerts\nalert only", COLORS["warn_bg"], COLORS["warn_border"], False),
            (
                "Policy merge\ncommands.yaml ← ios-xe-policy.yaml\nalways_block + denied allow_groups",
                COLORS["dc_bg"],
                COLORS["dc_border"],
                False,
            ),
            ("install-clawlab-guardrail-rules.sh", COLORS["dc_bg"], COLORS["dc_border"], False),
        ],
    )

    draw_column(
        draw,
        2,
        "3 · SSH-OPS MCP — Write Gate",
        [
            ("run_command\nread-only allowlist", COLORS["mcp_bg"], COLORS["mcp_border"], False),
            (
                "propose_change\nios-xe-policy.yaml · 60 allow_groups\ndefault deny",
                COLORS["mcp_bg"],
                COLORS["mcp_border"],
                False,
            ),
            (
                "Per-group access\nAlways deny · Approval required · Always allow",
                COLORS["mcp_orange_bg"],
                COLORS["mcp_orange_border"],
                False,
            ),
            ("Four-eyes gate\nforbid_self_approval", COLORS["mcp_orange_bg"], COLORS["mcp_orange_border"], False),
            ("Pending Changes Queue", COLORS["mcp_orange_bg"], COLORS["mcp_orange_border"], False),
            ("Approve / Reject\ndifferent claw-auth user", COLORS["mcp_orange_bg"], COLORS["mcp_orange_border"], False),
            (
                "apply_change\nbackup → push → verify → write mem",
                COLORS["mcp_bg"],
                COLORS["mcp_border"],
                False,
            ),
            ("Direct writes blocked\nno bash shortcut bypass", COLORS["crit_bg"], COLORS["crit_border"], True),
        ],
    )

    draw_column(
        draw,
        3,
        "4 · NOTIFICATIONS",
        [
            ("Webex · change event\non successful apply", COLORS["notify_bg"], COLORS["notify_border"], False),
            (
                "Webex · block / guardrail\naudit.db → dc-webex-bridge",
                COLORS["notify_bg"],
                COLORS["notify_border"],
                False,
            ),
            (
                "Webex · self-approval blocked\nfour-eyes violation",
                COLORS["notify_bg"],
                COLORS["notify_border"],
                False,
            ),
        ],
    )

    mid_y = COL_TOP + COL_H // 2
    for i in range(3):
        draw_arrow(draw, col_x(i) + COL_W + 4, col_x(i + 1) - 4, mid_y)

    leg_y = H - MARGIN - LEGEND_H + 10
    draw.rounded_rectangle(
        (MARGIN, leg_y, W - MARGIN, H - MARGIN),
        radius=12,
        outline="#484f58",
        width=2,
    )
    legend = (
        "Legend:  "
        "CRITICAL hard block  ·  "
        "HIGH advisory  ·  "
        "Human approval / four-eyes  ·  "
        "Allowed apply path"
    )
    lb = draw.textbbox((0, 0), legend, font=FONT_LEG)
    draw.text(((W - (lb[2] - lb[0])) // 2, leg_y + 28), legend, fill=COLORS["muted"], font=FONT_LEG)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, format="PNG", optimize=True)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
