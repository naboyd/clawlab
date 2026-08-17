#!/usr/bin/env python3
"""Render docs/clawlab-system-internals.png — how clawlab auth and data flow work.

  python3 admin-access/render-system-internals-diagram.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "clawlab-system-internals.png"

W, H = 1480, 1720
MARGIN = 44
BG = "#f4f1ea"
GRID = "#ddd8cc"
INK = "#2c2825"
INK_MUTED = "#5c5650"
ARROW = "#3d3832"

PALETTE = {
    "client": ("#dbeafe", "#2563eb"),
    "edge": ("#e0e7ff", "#4338ca"),
    "auth": ("#fce7f3", "#db2777"),
    "service": ("#d1fae5", "#059669"),
    "guard": ("#ffedd5", "#ea580c"),
    "data": ("#f3f4f6", "#6b7280"),
    "fleet": ("#cffafe", "#0891b2"),
}


def load_font(size: int, *, hand: bool = False, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if hand:
        candidates = ["/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf"]
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


FONT_TITLE = load_font(38, hand=True)
FONT_LAYER = load_font(20, hand=True)
FONT_NAME = load_font(22, hand=True)
FONT_PORTS = load_font(14, bold=True)
FONT_BLURB = load_font(15)

Rect = tuple[int, int, int, int]


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


def cx(r: Rect) -> int:
    return (r[0] + r[2]) // 2


def cy(r: Rect) -> int:
    return (r[1] + r[3]) // 2


def draw_path(draw: ImageDraw.ImageDraw, pts: list[tuple[int, int]]) -> None:
    for i in range(len(pts) - 1):
        draw.line([pts[i], pts[i + 1]], fill=ARROW, width=3)
    a, b = pts[-2], pts[-1]
    if abs(b[1] - a[1]) >= abs(b[0] - a[0]):
        draw.polygon([(b[0], b[1]), (b[0] - 8, b[1] - 12), (b[0] + 8, b[1] - 12)], fill=ARROW)
    else:
        draw.polygon([(b[0], b[1]), (b[0] - 12, b[1] - 8), (b[0] - 12, b[1] + 8)], fill=ARROW)


def draw_component(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, kind: str, name: str, ports: str, blurb: str) -> Rect:
    fill, border = PALETTE[kind]
    draw.rounded_rectangle((x, y, x + w, y + h), radius=14, fill=fill, outline=border, width=3)
    pad = 12
    ty = y + pad
    for line in wrap(name, FONT_NAME, w - 2 * pad):
        draw.text((x + pad, ty), line, fill=INK, font=FONT_NAME)
        ty += FONT_NAME.size + 3
    for line in wrap(ports, FONT_PORTS, w - 2 * pad):
        draw.text((x + pad, ty), line, fill=INK_MUTED, font=FONT_PORTS)
        ty += FONT_PORTS.size + 2
    ty += 2
    for line in wrap(blurb, FONT_BLURB, w - 2 * pad):
        draw.text((x + pad, ty), line, fill=INK_MUTED, font=FONT_BLURB)
        ty += FONT_BLURB.size + 2
    return (x, y, x + w, y + h)


def main() -> None:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    for x in range(0, W, 28):
        draw.line([(x, 0), (x, H)], fill=GRID, width=1)
    for y in range(0, H, 28):
        draw.line([(0, y), (W, y)], fill=GRID, width=1)

    title = "Clawlab — How It Works (Auth & Data Flow)"
    draw.text(((W - FONT_TITLE.getlength(title)) / 2, MARGIN), title, fill=INK, font=FONT_TITLE)

    boxes: dict[str, Rect] = {}
    y = MARGIN + 64
    layer_y: list[tuple[str, int]] = []

    def layer(label: str) -> None:
        nonlocal y
        layer_y.append((label, y))
        y += 26

    def row(items: list[tuple[str, str, str, str, str, int, int]], gap: int = 24) -> None:
        nonlocal y
        total_w = sum(w for *_, w, _ in items) + gap * (len(items) - 1)
        x = (W - total_w) // 2
        max_h = max(h for *_, _, h in items)
        for nid, kind, name, ports, blurb, w, h in items:
            boxes[nid] = draw_component(draw, x, y, w, h, kind, name, ports, blurb)
            x += w + gap
        y += max_h + 40

    layer("Clients")
    row([
        ("browser", "client", "Browser", "HTTPS", "Portal hub · MCP Admin · DefenseClaw", 200, 100),
        ("oc_ui", "client", "OpenClaw UI", "WSS /openclaw/", "Gateway token + device pairing", 220, 100),
        ("cursor", "client", "External MCP", "Cursor · Claude", "Bearer skops_ PAT on :8767", 220, 100),
    ])

    layer("Edge & identity")
    row([
        ("nginx", "edge", "nginx portal", ":8443 / :8083", "auth_request → claw-auth /verify", 260, 108),
        ("auth", "auth", "claw-auth", ":8780", "Session cookie · users.db · MCP tokens", 260, 108),
        ("proxy", "auth", "MCP identity proxy", ":8767 TLS", "Validates PAT · clawBind · shared bearer", 300, 108),
    ])

    layer("Agent & guardrails")
    row([
        ("gateway", "service", "OpenClaw gateway", ":18789", "Agent · MCP client · clawlab-mcp-identity plugin", 300, 118),
        ("dc", "guard", "DefenseClaw", ":4000 proxy", "Prompt/tool inspect · regex + judge", 260, 118),
        ("ollama", "service", "Ollama", ":11434", "Agent LLM · local judge", 200, 118),
    ])

    layer("Operations")
    row([
        ("mcp", "service", "ssh-ops MCP", ":8766 internal", "run_command · propose/apply · RBAC", 280, 118),
        ("gui", "service", "ssh-ops GUI", ":8765", "Hosts · changes · policy tab", 240, 118),
        ("policy", "data", "Policy store", "ios-xe-policy.yaml", "60 allow_groups · four-eyes", 260, 118),
    ])

    layer("Targets & alerts")
    row([
        ("fleet", "fleet", "Network fleet", "SSH IOS-XE", "Backup · push · verify", 280, 100),
        ("webex", "data", "Webex & audit", "audit.db", "Blocks · approvals · violations", 280, 100),
    ])

    b = boxes
    paths = [
        [(cx(b["browser"]), b["browser"][3]), (cx(b["nginx"]), b["nginx"][1])],
        [(cx(b["nginx"]), b["nginx"][3]), (cx(b["auth"]), b["auth"][1])],
        [(b["nginx"][2] - 20, cy(b["nginx"])), (b["oc_ui"][0], cy(b["oc_ui"]))],
        [(cx(b["oc_ui"]), b["oc_ui"][3]), (cx(b["gateway"]), b["gateway"][1])],
        [(cx(b["cursor"]), b["cursor"][3]), (cx(b["proxy"]), b["proxy"][1])],
        [(cx(b["gateway"]), b["gateway"][3]), (cx(b["proxy"]), cy(b["proxy"]))],
        [(cx(b["proxy"]), b["proxy"][3]), (cx(b["mcp"]), b["mcp"][1])],
        [(cx(b["gateway"]), cy(b["gateway"])), (b["dc"][0], cy(b["dc"]))],
        [(b["dc"][2], cy(b["dc"])), (b["ollama"][0], cy(b["ollama"]))],
        [(b["auth"][2], cy(b["auth"])), (b["gui"][0], cy(b["gui"]))],
        [(cx(b["mcp"]), b["mcp"][3]), (cx(b["fleet"]), b["fleet"][1])],
        [(cx(b["dc"]), b["dc"][3]), (cx(b["webex"]), b["webex"][1])],
        [(b["policy"][2], cy(b["policy"])), (b["mcp"][2], cy(b["mcp"]))],
    ]
    for pts in paths:
        draw_path(draw, pts)

    for text, y_pos in layer_y:
        draw.text(((W - FONT_LAYER.getlength(text)) / 2, y_pos), text, fill=INK_MUTED, font=FONT_LAYER)

    legend = (
        "Portal: session cookie  ·  OpenClaw MCP: clawBind or PAT  ·  "
        "External MCP: PAT on :8767 only  ·  Raw :8766 never for clients"
    )
    draw.text(((W - FONT_BLURB.getlength(legend)) / 2, H - MARGIN - 8), legend, fill=INK_MUTED, font=FONT_BLURB)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, format="PNG", optimize=True)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
