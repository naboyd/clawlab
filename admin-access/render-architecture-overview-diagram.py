#!/usr/bin/env python3
"""Render docs/clawlab-architecture-overview.png (whiteboard system component view).

Connectors run in left/right gutters and layer gaps — drawn under boxes so
lines never cross component text.

  python3 admin-access/render-architecture-overview-diagram.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "clawlab-architecture-overview.png"

W, H = 1400, 1680
MARGIN = 48
LEFT_BUS = 56
RIGHT_BUS = W - 56
BG = "#f4f1ea"
GRID = "#ddd8cc"
INK = "#2c2825"
INK_MUTED = "#5c5650"
ARROW = "#3d3832"

PALETTE = {
    "user": ("#dbeafe", "#2563eb"),
    "edge": ("#e0e7ff", "#4338ca"),
    "auth": ("#fce7f3", "#db2777"),
    "agent": ("#d1fae5", "#059669"),
    "guard": ("#ffedd5", "#ea580c"),
    "infra": ("#e9d5ff", "#9333ea"),
    "mcp": ("#bbf7d0", "#16a34a"),
    "data": ("#f3f4f6", "#6b7280"),
    "fleet": ("#cffafe", "#0891b2"),
    "notify": ("#fef3c7", "#d97706"),
}

Rect = tuple[int, int, int, int]


def load_font(size: int, *, hand: bool = False, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if hand:
        candidates = [
            "/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf",
            "/System/Library/Fonts/Supplemental/Noteworthy-Bold.ttf",
            "/System/Library/Fonts/Supplemental/ChalkboardSE-Bold.ttf",
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


FONT_TITLE = load_font(42, hand=True)
FONT_LAYER = load_font(22, hand=True)
FONT_NAME = load_font(26, hand=True)
FONT_PORTS = load_font(15, bold=True)
FONT_BLURB = load_font(16)


def draw_grid(img: Image.Image, step: int = 28) -> None:
    draw = ImageDraw.Draw(img)
    for x in range(0, W, step):
        draw.line([(x, 0), (x, H)], fill=GRID, width=1)
    for y in range(0, H, step):
        draw.line([(0, y), (W, y)], fill=GRID, width=1)


def wrap_lines(text: str, font: ImageFont.ImageFont, max_w: int) -> list[str]:
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


def center_x(w: int) -> int:
    return (W - w) // 2


def cx(rect: Rect) -> int:
    return (rect[0] + rect[2]) // 2


def cy(rect: Rect) -> int:
    return (rect[1] + rect[3]) // 2


def gutter_between(top: Rect, bottom: Rect) -> int:
    return top[3] + (bottom[1] - top[3]) // 2


def draw_arrowhead(draw: ImageDraw.ImageDraw, x: int, y: int, direction: str) -> None:
    size = 10
    if direction == "down":
        draw.polygon([(x, y), (x - size, y - size), (x + size, y - size)], fill=ARROW)
    elif direction == "right":
        draw.polygon([(x, y), (x - size, y - size), (x - size, y + size)], fill=ARROW)
    elif direction == "left":
        draw.polygon([(x, y), (x + size, y - size), (x + size, y + size)], fill=ARROW)


def draw_path(draw: ImageDraw.ImageDraw, pts: list[tuple[int, int]]) -> None:
    for i in range(len(pts) - 1):
        draw.line([pts[i], pts[i + 1]], fill=ARROW, width=3)
    a, b = pts[-2], pts[-1]
    if abs(b[0] - a[0]) > abs(b[1] - a[1]):
        draw_arrowhead(draw, b[0], b[1], "right" if b[0] > a[0] else "left")
    else:
        draw_arrowhead(draw, b[0], b[1], "down")


def compute_layout() -> tuple[dict[str, Rect], dict[str, dict], list[tuple[str, int]]]:
    """Return boxes (x1,y1,x2,y2), specs, and layer label positions."""
    boxes: dict[str, Rect] = {}
    specs: dict[str, dict] = {}
    labels: list[tuple[str, int]] = []
    y = MARGIN + 56
    row_gap = 56
    gap = 36

    def add_layer(name: str) -> None:
        nonlocal y
        labels.append((name, y))
        y += 28

    def add_box(nid: str, kind: str, name: str, ports: str, blurb: str, x: int, w: int, h: int) -> None:
        nonlocal y
        specs[nid] = {"kind": kind, "name": name, "ports": ports, "blurb": blurb, "x": x, "y": y, "w": w, "h": h}
        boxes[nid] = (x, y, x + w, y + h)
        y += h + row_gap

    add_layer("People")
    add_box("operator", "user", "Operators", "Browser", "Chat · approve changes · edit policy", center_x(280), 280, 108)

    add_layer("Edge")
    add_box(
        "portal", "edge", "Unified portal",
        "nginx :8443  ·  local-full :8083",
        "One front door — hub · MCP · DC · OpenClaw proxy",
        center_x(520), 520, 118,
    )

    add_layer("Identity")
    add_box(
        "auth", "auth", "claw-auth", ":8780 loopback",
        "Sessions · four-eyes identity · device admin",
        center_x(300), 300, 108,
    )

    add_layer("Agent plane")
    aw, ah = 280, 128
    agent_y = y
    total = 3 * aw + 2 * gap
    x0 = (W - total) // 2
    agents = [
        ("openclaw", "agent", "OpenClaw", "gateway :18789", "LLM agent · MCP client · Control UI"),
        ("defenseclaw", "guard", "DefenseClaw", "proxy :4000 · sidecar :18970", "Prompt + tool inspect · judge · guardrails"),
        ("ollama", "infra", "Ollama", ":11434 loopback", "Agent model + local judge"),
    ]
    for i, (nid, kind, name, ports, blurb) in enumerate(agents):
        x = x0 + i * (aw + gap)
        specs[nid] = {"kind": kind, "name": name, "ports": ports, "blurb": blurb, "x": x, "y": agent_y, "w": aw, "h": ah}
        boxes[nid] = (x, agent_y, x + aw, agent_y + ah)
    y = agent_y + ah + row_gap

    add_layer("Operations")
    ow, oh = 380, 118
    op_y = y
    total = 2 * ow + gap
    x0 = (W - total) // 2
    ops = [
        ("mcp", "mcp", "ssh-ops MCP", "MCP :8766 · GUI :8765 · Podman", "Write gate · propose · approve · apply"),
        ("policy", "data", "Policy & inventory", "hosts.yaml · ios-xe-policy.yaml", "60 allow_groups · fleet targets"),
    ]
    for i, (nid, kind, name, ports, blurb) in enumerate(ops):
        x = x0 + i * (ow + gap)
        specs[nid] = {"kind": kind, "name": name, "ports": ports, "blurb": blurb, "x": x, "y": op_y, "w": ow, "h": oh}
        boxes[nid] = (x, op_y, x + ow, op_y + oh)
    y = op_y + oh + row_gap

    add_layer("Targets")
    add_box(
        "fleet", "fleet", "Network fleet", "IOS-XE · SSH",
        "Switches · lab devices · backup → push → verify",
        center_x(480), 480, 108,
    )

    add_layer("Observability")
    add_box(
        "notify", "notify", "Webex & audit", "audit.db · dc-webex-bridge",
        "Blocks · applies · four-eyes violations",
        center_x(440), 440, 108,
    )

    return boxes, specs, labels


def build_edge_paths(boxes: dict[str, Rect]) -> list[list[tuple[int, int]]]:
    """Explicit polylines in gutters — no segments through box interiors."""
    b = boxes
    paths: list[list[tuple[int, int]]] = []

    # Center spine
    paths.append([(cx(b["operator"]), b["operator"][3]), (cx(b["portal"]), b["portal"][1])])
    paths.append([(cx(b["portal"]), b["portal"][3]), (cx(b["auth"]), b["auth"][1])])

    # Portal → OpenClaw via left bus (avoids auth box)
    gy = gutter_between(b["auth"], b["openclaw"])
    paths.append([
        (b["portal"][0] + 48, b["portal"][3]),
        (b["portal"][0] + 48, gy),
        (LEFT_BUS, gy),
        (LEFT_BUS, b["openclaw"][1] - 18),
        (cx(b["openclaw"]), b["openclaw"][1] - 18),
        (cx(b["openclaw"]), b["openclaw"][1]),
    ])

    # Auth → MCP via left bus (avoids agent row)
    gy = gutter_between(b["auth"], b["openclaw"])
    paths.append([
        (b["auth"][0] + 24, b["auth"][3]),
        (b["auth"][0] + 24, gy),
        (LEFT_BUS, gy),
        (LEFT_BUS, b["mcp"][1] - 18),
        (cx(b["mcp"]), b["mcp"][1] - 18),
        (cx(b["mcp"]), b["mcp"][1]),
    ])

    # OpenClaw → MCP (left column, straight gutter)
    gy = gutter_between(b["openclaw"], b["mcp"])
    paths.append([
        (cx(b["openclaw"]), b["openclaw"][3]),
        (cx(b["openclaw"]), gy),
        (cx(b["mcp"]), gy),
        (cx(b["mcp"]), b["mcp"][1]),
    ])

    # Agent row — horizontal in the gap between boxes (mid-row)
    paths.append([
        (b["openclaw"][2], cy(b["openclaw"])),
        (b["defenseclaw"][0], cy(b["defenseclaw"])),
    ])
    paths.append([
        (b["defenseclaw"][2], cy(b["defenseclaw"])),
        (b["ollama"][0], cy(b["ollama"])),
    ])

    # DefenseClaw → Policy via right bus (avoids MCP)
    gy = gutter_between(b["openclaw"], b["mcp"])
    paths.append([
        (b["defenseclaw"][2] - 24, b["defenseclaw"][3]),
        (b["defenseclaw"][2] - 24, gy),
        (RIGHT_BUS, gy),
        (RIGHT_BUS, b["policy"][1] - 18),
        (cx(b["policy"]), b["policy"][1] - 18),
        (cx(b["policy"]), b["policy"][1]),
    ])

    # MCP → Policy (horizontal through row gap between agent and operations)
    row_gap_y = b["openclaw"][3] + (b["mcp"][1] - b["openclaw"][3]) // 2
    paths.append([
        (b["mcp"][2], cy(b["mcp"])),
        (b["mcp"][2], row_gap_y),
        (b["policy"][0], row_gap_y),
        (b["policy"][0], cy(b["policy"])),
    ])

    # MCP → Fleet → Notify (center spine below operations)
    gy1 = gutter_between(b["mcp"], b["fleet"])
    paths.append([
        (cx(b["mcp"]), b["mcp"][3]),
        (cx(b["mcp"]), gy1),
        (cx(b["fleet"]), gy1),
        (cx(b["fleet"]), b["fleet"][1]),
    ])
    paths.append([(cx(b["fleet"]), b["fleet"][3]), (cx(b["notify"]), b["notify"][1])])

    return paths


def draw_component(draw: ImageDraw.ImageDraw, spec: dict) -> None:
    x, y, bw, bh = spec["x"], spec["y"], spec["w"], spec["h"]
    fill, border = PALETTE[spec["kind"]]
    draw.rounded_rectangle((x, y, x + bw, y + bh), radius=16, fill=fill, outline=border, width=3)
    pad = 14
    inner = bw - 2 * pad
    ty = y + pad
    for line in wrap_lines(spec["name"], FONT_NAME, inner):
        draw.text((x + pad, ty), line, fill=INK, font=FONT_NAME)
        ty += FONT_NAME.size + 4
    ty += 2
    for line in wrap_lines(spec["ports"], FONT_PORTS, inner):
        draw.text((x + pad, ty), line, fill=INK_MUTED, font=FONT_PORTS)
        ty += FONT_PORTS.size + 3
    ty += 4
    for line in wrap_lines(spec["blurb"], FONT_BLURB, inner):
        draw.text((x + pad, ty), line, fill=INK_MUTED, font=FONT_BLURB)
        ty += FONT_BLURB.size + 2


def main() -> None:
    boxes, specs, layer_labels = compute_layout()
    paths = build_edge_paths(boxes)

    img = Image.new("RGB", (W, H), BG)
    draw_grid(img)
    draw = ImageDraw.Draw(img)

    title = "Clawlab — System Architecture"
    tw = FONT_TITLE.getlength(title)
    draw.text(((W - tw) / 2, MARGIN), title, fill=INK, font=FONT_TITLE)

    # 1) Connectors under boxes
    for pts in paths:
        draw_path(draw, pts)

    # 2) Layer labels
    for text, y_pos in layer_labels:
        lw = FONT_LAYER.getlength(text)
        draw.text((W // 2 - lw / 2, y_pos), text, fill=INK_MUTED, font=FONT_LAYER)

    # 3) Boxes on top
    for nid in (
        "operator", "portal", "auth",
        "openclaw", "defenseclaw", "ollama",
        "mcp", "policy", "fleet", "notify",
    ):
        draw_component(draw, specs[nid])

    foot = "Detail: docs/clawlab-policy-enforcement-flow.png  ·  Regenerate: python3 admin-access/render-architecture-overview-diagram.py"
    fw = FONT_BLURB.getlength(foot)
    draw.text(((W - fw) / 2, H - MARGIN - 8), foot, fill=INK_MUTED, font=FONT_BLURB)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, format="PNG", optimize=True)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
