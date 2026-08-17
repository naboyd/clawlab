#!/usr/bin/env python3
"""Render docs/clawlab-user-journey.png — operator view of clawlab.

  python3 admin-access/render-user-journey-diagram.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "clawlab-user-journey.png"

W, H = 1320, 1680
MARGIN = 44
BG = "#f4f1ea"
GRID = "#ddd8cc"
INK = "#2c2825"
INK_MUTED = "#5c5650"
ARROW = "#3d3832"

PALETTE = {
    "start": ("#dbeafe", "#2563eb"),
    "hub": ("#e0e7ff", "#4338ca"),
    "work": ("#d1fae5", "#059669"),
    "admin": ("#fce7f3", "#db2777"),
    "external": ("#ffedd5", "#ea580c"),
    "warn": ("#fef3c7", "#d97706"),
}


def load_font(size: int, *, hand: bool = False, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if hand:
        candidates = [
            "/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf",
            "/System/Library/Fonts/Supplemental/Noteworthy-Bold.ttf",
        ]
    elif bold:
        candidates = [
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
    else:
        candidates = [
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    for path in candidates:
        p = Path(path)
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


FONT_TITLE = load_font(40, hand=True)
FONT_STEP = load_font(22, bold=True)
FONT_NAME = load_font(24, hand=True)
FONT_BODY = load_font(16)
FONT_NOTE = load_font(14)


def wrap(text: str, font: ImageFont.ImageFont, max_w: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        cur = words[0]
        for w in words[1:]:
            trial = f"{cur} {w}"
            if font.getlength(trial) <= max_w:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


def draw_connector(draw: ImageDraw.ImageDraw, x1: int, y1: int, x2: int, y2: int) -> None:
    draw.line([(x1, y1), (x2, y2)], fill=ARROW, width=3)
    if y2 > y1:
        draw.polygon([(x2, y2), (x2 - 8, y2 - 12), (x2 + 8, y2 - 12)], fill=ARROW)


def draw_box(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    kind: str,
    step: str,
    title: str,
    body: str,
) -> tuple[int, int, int, int]:
    fill, border = PALETTE[kind]
    draw.rounded_rectangle((x, y, x + w, y + h), radius=14, fill=fill, outline=border, width=3)
    pad = 16
    ty = y + pad
    draw.text((x + pad, ty), step, fill=INK_MUTED, font=FONT_STEP)
    ty += FONT_STEP.size + 6
    for line in wrap(title, FONT_NAME, w - 2 * pad):
        draw.text((x + pad, ty), line, fill=INK, font=FONT_NAME)
        ty += FONT_NAME.size + 4
    ty += 4
    for line in wrap(body, FONT_BODY, w - 2 * pad):
        draw.text((x + pad, ty), line, fill=INK_MUTED, font=FONT_BODY)
        ty += FONT_BODY.size + 3
    return (x, y, x + w, y + h)


def main() -> None:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    for x in range(0, W, 28):
        draw.line([(x, 0), (x, H)], fill=GRID, width=1)
    for y in range(0, H, 28):
        draw.line([(0, y), (W, y)], fill=GRID, width=1)

    title = "Clawlab — User Journey"
    draw.text(((W - FONT_TITLE.getlength(title)) / 2, MARGIN), title, fill=INK, font=FONT_TITLE)
    subtitle = "What operators and admins do day to day"
    draw.text(
        ((W - FONT_NOTE.getlength(subtitle)) / 2, MARGIN + 48),
        subtitle,
        fill=INK_MUTED,
        font=FONT_NOTE,
    )

    bx = MARGIN + 40
    bw = W - 2 * (MARGIN + 40)
    y = MARGIN + 96
    gap = 28
    prev_bottom = None

    steps = [
        ("start", "1", "Bookmark the portal", "One URL for everything:\nhttps://<host>:8443/  (lab HTTP: :8083)"),
        ("hub", "2", "Sign in once", "claw-auth username + password.\nSame login for all hub tabs."),
        ("hub", "3", "Use the hub tabs", "MCP Admin · DefenseClaw · Users · MCP tokens · OpenClaw devices (admin)"),
        ("work", "4a", "OpenClaw (recommended)", "Hub → Open OpenClaw ↗\nLink includes gateway token + clawBind for MCP identity."),
        ("admin", "4b", "First browser only: approve device", "Admin → OpenClaw devices → Approve.\nThen Control UI connects."),
        ("work", "5", "Chat and propose changes", "Agent reads fleet via MCP.\npropose_change → Webex or portal approval (four-eyes)."),
        ("admin", "6", "Admin: policy & users", "DefenseClaw tab: rules & suppressions.\nUsers tab: roles operator / admin / superadmin."),
        ("external", "7", "Cursor / Claude Desktop (optional)", "Hub → MCP tokens → create skops_ PAT.\nConnect to https://<host>:8767/mcp"),
        ("warn", "8", "Bookmarked OpenClaw chat?", "Plain /openclaw/chat without clawBind needs a PAT:\nbash admin-access/set-openclaw-mcp-pat.sh"),
    ]

    for kind, step, title_t, body in steps:
        h = 88 + len(wrap(body, FONT_BODY, bw - 32)) * (FONT_BODY.size + 3)
        rect = draw_box(draw, bx, y, bw, h, kind, step, title_t, body)
        if prev_bottom is not None:
            draw_connector(draw, bx + bw // 2, prev_bottom, bx + bw // 2, y)
        prev_bottom = rect[3]
        y = rect[3] + gap

    foot = "Usage guide: docs/USER-GUIDE.md  ·  Regenerate: python3 admin-access/render-user-journey-diagram.py"
    draw.text(((W - FONT_NOTE.getlength(foot)) / 2, H - MARGIN - 6), foot, fill=INK_MUTED, font=FONT_NOTE)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, format="PNG", optimize=True)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
