#!/usr/bin/env python3
"""Render clawlab system internals — interactive HTML + simple component grid PNG.

  python3 admin-access/render-system-internals-diagram.py

Primary artifact: docs/clawlab-system-internals.html (tabbed flows, no crossing lines).
PNG is a layer grid for README thumbnails only.
"""
from __future__ import annotations

import html
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[1]
OUT_HTML = REPO / "docs" / "clawlab-system-internals.html"
OUT_PNG = REPO / "docs" / "clawlab-system-internals.png"

PALETTE = {
    "client": ("#dbeafe", "#2563eb"),
    "edge": ("#e0e7ff", "#4338ca"),
    "auth": ("#fce7f3", "#db2777"),
    "service": ("#d1fae5", "#059669"),
    "guard": ("#ffedd5", "#ea580c"),
    "data": ("#f3f4f6", "#6b7280"),
    "fleet": ("#cffafe", "#0891b2"),
}

FLOWS = [
    {
        "id": "overview",
        "title": "Overview",
        "subtitle": "Components by layer — use other tabs for step-by-step paths.",
        "steps": [],
        "lanes": [
            {
                "label": "Clients",
                "nodes": [
                    {"id": "browser", "kind": "client", "name": "Browser", "ports": "HTTPS",
                     "detail": "Portal hub, MCP Admin iframe, DefenseClaw iframe."},
                    {"id": "oc_ui", "kind": "client", "name": "OpenClaw UI", "ports": "WSS /openclaw/",
                     "detail": "New window from hub. Gateway token + device pairing."},
                    {"id": "cursor", "kind": "client", "name": "External MCP", "ports": "Cursor · Claude",
                     "detail": "Bearer skops_ PAT — never connect to raw :8766."},
                ],
            },
            {
                "label": "Edge & identity",
                "nodes": [
                    {"id": "nginx", "kind": "edge", "name": "nginx portal", "ports": ":8443 / :8083",
                     "detail": "Single public listener. auth_request on protected paths."},
                    {"id": "auth", "kind": "auth", "name": "claw-auth", "ports": ":8780",
                     "detail": "SQLite sessions, users, MCP tokens, device admin API."},
                    {"id": "proxy", "kind": "auth", "name": "MCP identity proxy", "ports": ":8767 TLS",
                     "detail": "PAT, clawBind, shared bearer → X-Auth-User to MCP."},
                ],
            },
            {
                "label": "Agent & guardrails",
                "nodes": [
                    {"id": "gateway", "kind": "service", "name": "OpenClaw gateway", "ports": ":18789",
                     "detail": "Agent, MCP client, clawlab-mcp-identity plugin."},
                    {"id": "dc", "kind": "guard", "name": "DefenseClaw", "ports": ":4000 proxy",
                     "detail": "Prompt/tool inspect — regex + optional LLM judge."},
                    {"id": "ollama", "kind": "service", "name": "Ollama", "ports": ":11434",
                     "detail": "Agent LLM and local judge model."},
                ],
            },
            {
                "label": "Operations",
                "nodes": [
                    {"id": "mcp", "kind": "service", "name": "ssh-ops MCP", "ports": ":8766 internal",
                     "detail": "run_command, propose_change, apply_change, RBAC."},
                    {"id": "gui", "kind": "service", "name": "ssh-ops GUI", "ports": ":8765",
                     "detail": "Hosts, changes, policy tab — portal auth only."},
                    {"id": "policy", "kind": "data", "name": "Policy store", "ports": "ios-xe-policy.yaml",
                     "detail": "Allow groups, four-eyes, IOS line validation."},
                ],
            },
            {
                "label": "Targets & alerts",
                "nodes": [
                    {"id": "fleet", "kind": "fleet", "name": "Network fleet", "ports": "SSH IOS-XE",
                     "detail": "Backup, push, verify — gated changes only."},
                    {"id": "webex", "kind": "data", "name": "Webex & audit", "ports": "audit.db",
                     "detail": "Blocks, approvals, drift alerts."},
                ],
            },
        ],
    },
    {
        "id": "portal",
        "title": "Portal session",
        "subtitle": "claw-auth cookie protects MCP Admin and DefenseClaw tabs.",
        "steps": [
            {"from": "browser", "to": "nginx", "label": "HTTPS :8443 hub login"},
            {"from": "nginx", "to": "auth", "label": "auth_request → /verify"},
            {"from": "auth", "to": "gui", "label": "session OK → proxy /ssh-ops/ + X-Auth-User"},
        ],
        "note": "DefenseClaw /defenseclaw/ uses the same claw-auth session. "
        "Direct http://127.0.0.1:8765/ returns 403 when CLAW_AUTH_REQUIRED=1.",
    },
    {
        "id": "openclaw",
        "title": "OpenClaw + MCP",
        "subtitle": "Control UI via gateway token; agent MCP via identity proxy (clawBind).",
        "steps": [
            {"from": "browser", "to": "nginx", "label": "hub → Open OpenClaw ↗"},
            {"from": "nginx", "to": "gateway", "label": "WSS /openclaw/ (no nginx auth)"},
            {"from": "gateway", "to": "proxy", "label": "MCP client → :8767 + clawBind"},
            {"from": "proxy", "to": "mcp", "label": "X-Auth-User + bearer → :8766"},
        ],
        "note": "In parallel: gateway → DefenseClaw :4000 → Ollama judge on tool/prompt calls. "
        "First browser visit: admin approves device on OpenClaw devices tab.",
    },
    {
        "id": "external",
        "title": "External MCP",
        "subtitle": "Cursor / Claude Desktop — PAT on :8767 only.",
        "steps": [
            {"from": "cursor", "to": "proxy", "label": "Bearer skops_… on :8767/mcp"},
            {"from": "proxy", "to": "auth", "label": "validate PAT (users.db)"},
            {"from": "proxy", "to": "mcp", "label": "forward identity → :8766"},
        ],
        "note": "Create PAT at portal hub → MCP tokens. Never expose :8766 to clients.",
    },
    {
        "id": "changes",
        "title": "Gated changes",
        "subtitle": "propose → policy → human approve → apply → fleet.",
        "steps": [
            {"from": "gateway", "to": "mcp", "label": "propose_change (verified MCP user)"},
            {"from": "mcp", "to": "policy", "label": "ios-xe allow_groups check"},
            {"from": "policy", "to": "gui", "label": "pending change in MCP Admin"},
            {"from": "gui", "to": "mcp", "label": "operator approves (four-eyes)"},
            {"from": "mcp", "to": "fleet", "label": "apply_change over SSH"},
            {"from": "fleet", "to": "webex", "label": "notify apply / config drift"},
        ],
        "note": "DefenseClaw may block dangerous tool calls before MCP. Blocks also notify Webex.",
    },
]

# Flat node registry for flow steps and detail panel.
NODES: dict[str, dict[str, str]] = {}
for flow in FLOWS:
    for lane in flow.get("lanes") or []:
        for node in lane["nodes"]:
            NODES[node["id"]] = node
    for step in flow.get("steps") or []:
        for key in ("from", "to"):
            nid = step[key]
            if nid not in NODES:
                NODES[nid] = {"id": nid, "kind": "data", "name": nid, "ports": "", "detail": ""}


def render_html() -> str:
    flows_json = html.escape(json.dumps(FLOWS, indent=2))
    nodes_json = html.escape(json.dumps(NODES, indent=2))
    palette_json = html.escape(json.dumps(PALETTE))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Clawlab — How It Works</title>
  <style>
    :root {{
      --bg: #e8e4dc;
      --panel: #fffdf8;
      --ink: #2c2825;
      --muted: #5c5650;
      --border: #3d3832;
      --accent: #4338ca;
      --flow: #3d3832;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); font-family: system-ui, -apple-system, sans-serif; color: var(--ink); }}
    header {{
      padding: 12px 20px; background: var(--panel); border-bottom: 2px solid var(--border);
      display: flex; flex-wrap: wrap; gap: 12px; align-items: center;
    }}
    header strong {{ margin-right: 8px; }}
    header a {{ color: var(--accent); text-decoration: none; margin-right: 14px; font-size: 14px; }}
    header a:hover {{ text-decoration: underline; }}
    .wrap {{ max-width: 1280px; margin: 0 auto; padding: 20px 16px 40px; }}
    h1 {{ font-size: 1.6rem; margin: 0 0 6px; font-weight: 650; }}
    .lead {{ color: var(--muted); margin: 0 0 20px; line-height: 1.55; max-width: 720px; }}
    .tabs {{
      display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px;
    }}
    .tab {{
      border: 2px solid var(--border); background: var(--panel); color: var(--ink);
      padding: 8px 14px; border-radius: 999px; cursor: pointer; font-size: 14px; font-weight: 600;
    }}
    .tab[aria-selected="true"] {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
    .layout {{
      display: grid; grid-template-columns: 1fr 280px; gap: 16px; align-items: start;
    }}
    @media (max-width: 900px) {{ .layout {{ grid-template-columns: 1fr; }} }}
    .canvas {{
      background: var(--panel); border: 2px solid var(--border); border-radius: 12px;
      padding: 20px; min-height: 420px;
    }}
    .flow-title {{ font-size: 1.1rem; font-weight: 650; margin: 0 0 4px; }}
    .flow-sub {{ color: var(--muted); font-size: 14px; margin: 0 0 20px; }}
    .lanes {{ display: flex; flex-direction: column; gap: 18px; }}
    .lane-label {{
      font-size: 12px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;
      color: var(--muted); margin-bottom: 8px; text-align: center;
    }}
    .lane-row {{ display: flex; flex-wrap: wrap; gap: 12px; justify-content: center; }}
    .node {{
      border: 2px solid; border-radius: 12px; padding: 10px 12px; min-width: 160px; max-width: 220px;
      cursor: pointer; transition: transform 0.12s, box-shadow 0.12s;
    }}
    .node:hover, .node.active {{ transform: translateY(-2px); box-shadow: 0 6px 16px rgba(0,0,0,0.12); }}
    .node.dim {{ opacity: 0.35; }}
    .node-name {{ font-weight: 650; font-size: 15px; margin-bottom: 2px; }}
    .node-ports {{ font-size: 12px; font-weight: 600; color: var(--muted); margin-bottom: 4px; }}
    .node-hint {{ font-size: 12px; color: var(--muted); line-height: 1.35; }}
    .steps {{ display: flex; flex-direction: column; align-items: center; gap: 0; }}
    .step-row {{ display: flex; flex-direction: column; align-items: center; width: 100%; max-width: 360px; }}
    .step-arrow {{
      display: flex; flex-direction: column; align-items: center; color: var(--muted); font-size: 12px;
      padding: 6px 0; width: 100%;
    }}
    .step-arrow::before {{
      content: ''; width: 2px; height: 20px; background: var(--flow); margin-bottom: 4px;
    }}
    .step-arrow::after {{
      content: ''; width: 0; height: 0;
      border-left: 7px solid transparent; border-right: 7px solid transparent;
      border-top: 10px solid var(--flow);
    }}
    .step-label {{
      background: #f4f1ea; border: 1px solid #ccc5b8; border-radius: 6px; padding: 4px 10px;
      font-size: 12px; font-weight: 600; margin-top: 4px; text-align: center;
    }}
    .flow-note {{
      margin-top: 20px; padding: 10px 14px; background: #fef3c7; border: 1px solid #d97706;
      border-radius: 8px; font-size: 13px; color: #78350f;
    }}
    .detail {{
      background: var(--panel); border: 2px solid var(--border); border-radius: 12px;
      padding: 16px; position: sticky; top: 16px;
    }}
    .detail h2 {{ font-size: 14px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin: 0 0 10px; }}
    .detail .pick {{ color: var(--muted); font-size: 14px; line-height: 1.5; }}
    .detail-name {{ font-size: 1.15rem; font-weight: 700; margin: 0 0 4px; }}
    .detail-ports {{ font-size: 13px; font-weight: 600; color: var(--muted); margin-bottom: 10px; }}
    .detail-body {{ font-size: 14px; line-height: 1.55; color: var(--ink); }}
    .legend {{
      margin-top: 20px; font-size: 13px; color: var(--muted); line-height: 1.5;
      padding-top: 16px; border-top: 1px solid #ccc5b8;
    }}
    footer {{ margin-top: 24px; font-size: 13px; color: var(--muted); }}
    code {{ background: #f4f1ea; padding: 1px 5px; border-radius: 4px; font-size: 0.92em; }}
  </style>
</head>
<body>
  <header>
    <strong>Clawlab diagrams</strong>
    <a href="USER-GUIDE.md">Usage guide</a>
    <a href="ARCHITECTURE.md">Architecture</a>
    <a href="clawlab-user-journey.html">User journey</a>
    <a href="clawlab-architecture-overview.html">Component map</a>
    <a href="clawlab-policy-enforcement-flow.html">Policy flow</a>
  </header>
  <div class="wrap">
    <h1>How it works — auth &amp; data flow</h1>
    <p class="lead">Interactive view of clawlab internals. Pick a flow tab to see one path at a time
    (no crossing lines). Click any component for details.</p>
    <div class="tabs" id="tabs" role="tablist"></div>
    <div class="layout">
      <div class="canvas" id="canvas" role="tabpanel"></div>
      <aside class="detail" id="detail">
        <h2>Component</h2>
        <p class="pick">Click a box to see ports and role in this stack.</p>
      </aside>
    </div>
    <p class="legend">
      <strong>Rules of thumb:</strong> Portal = session cookie · OpenClaw MCP = clawBind or shared bearer on
      <code>:8767</code> · External MCP = PAT <code>skops_…</code> on <code>:8767</code> only ·
      Raw MCP <code>:8766</code> is internal.
    </p>
    <footer>Regenerate: <code>python3 admin-access/render-system-internals-diagram.py</code>
    · Static grid PNG: <code>clawlab-system-internals.png</code></footer>
  </div>
  <script id="flows-data" type="application/json">{flows_json}</script>
  <script id="nodes-data" type="application/json">{nodes_json}</script>
  <script id="palette-data" type="application/json">{palette_json}</script>
  <script>
    const FLOWS = JSON.parse(document.getElementById('flows-data').textContent);
    const NODES = JSON.parse(document.getElementById('nodes-data').textContent);
    const PALETTE = JSON.parse(document.getElementById('palette-data').textContent);

    let activeFlow = FLOWS[0].id;
    let activeNode = null;

    function nodeStyle(kind) {{
      const [fill, border] = PALETTE[kind] || PALETTE.data;
      return `background:${{fill}};border-color:${{border}}`;
    }}

    function renderNode(n, {{ highlight = false, dim = false }} = {{}}) {{
      const cls = ['node'];
      if (highlight) cls.push('active');
      if (dim) cls.push('dim');
      return `<div class="${{cls.join(' ')}}" data-id="${{n.id}}" style="${{nodeStyle(n.kind)}}" tabindex="0">
        <div class="node-name">${{n.name}}</div>
        <div class="node-ports">${{n.ports}}</div>
        <div class="node-hint">${{n.detail}}</div>
      </div>`;
    }}

    function involvedInFlow(flow) {{
      const ids = new Set();
      (flow.steps || []).forEach(s => {{ ids.add(s.from); ids.add(s.to); }});
      return ids;
    }}

    function renderOverview(flow) {{
      let html = `<p class="flow-title">${{flow.title}}</p><p class="flow-sub">${{flow.subtitle}}</p><div class="lanes">`;
      for (const lane of flow.lanes) {{
        html += `<div><div class="lane-label">${{lane.label}}</div><div class="lane-row">`;
        for (const n of lane.nodes) {{
          html += renderNode(n, {{ highlight: activeNode === n.id }});
        }}
        html += '</div></div>';
      }}
      html += '</div>';
      return html;
    }}

    function renderFlowSteps(flow) {{
      let html = `<p class="flow-title">${{flow.title}}</p><p class="flow-sub">${{flow.subtitle}}</p><div class="steps">`;
      flow.steps.forEach((step, i) => {{
        if (i === 0) {{
          html += `<div class="step-row">${{renderNode(NODES[step.from], {{ highlight: activeNode === step.from }})}}</div>`;
        }}
        html += `<div class="step-arrow"><span class="step-label">${{step.label}}</span></div>`;
        html += `<div class="step-row">${{renderNode(NODES[step.to], {{ highlight: activeNode === step.to }})}}</div>`;
      }});
      html += '</div>';
      if (flow.note) html += `<div class="flow-note">${{flow.note}}</div>`;
      return html;
    }}

    function showDetail(id) {{
      const panel = document.getElementById('detail');
      if (!id || !NODES[id]) {{
        panel.innerHTML = '<h2>Component</h2><p class="pick">Click a box to see ports and role in this stack.</p>';
        return;
      }}
      const n = NODES[id];
      panel.innerHTML = `<h2>Component</h2>
        <div class="detail-name">${{n.name}}</div>
        <div class="detail-ports">${{n.ports}}</div>
        <div class="detail-body">${{n.detail}}</div>`;
    }}

    function renderCanvas() {{
      const flow = FLOWS.find(f => f.id === activeFlow);
      const canvas = document.getElementById('canvas');
      if (flow.lanes) canvas.innerHTML = renderOverview(flow);
      else canvas.innerHTML = renderFlowSteps(flow);
      canvas.querySelectorAll('.node').forEach(el => {{
        el.addEventListener('click', () => {{
          activeNode = el.dataset.id;
          showDetail(activeNode);
          renderCanvas();
        }});
      }});
    }}

    function renderTabs() {{
      const tabs = document.getElementById('tabs');
      tabs.innerHTML = FLOWS.map(f =>
        `<button class="tab" role="tab" aria-selected="${{f.id === activeFlow}}" data-id="${{f.id}}">${{f.title}}</button>`
      ).join('');
      tabs.querySelectorAll('.tab').forEach(btn => {{
        btn.addEventListener('click', () => {{
          activeFlow = btn.dataset.id;
          activeNode = null;
          showDetail(null);
          renderTabs();
          renderCanvas();
        }});
      }});
    }}

    renderTabs();
    renderCanvas();
  </script>
</body>
</html>
"""


def load_font(size: int, *, hand: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if hand:
        candidates = ["/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf"]
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


def render_png_grid() -> None:
    """Simple layer grid for README thumbnails — no crossing arrows."""
    overview = FLOWS[0]
    lanes = overview["lanes"]
    W, H = 1400, 200 + sum(130 for _ in lanes)
    MARGIN = 40
    BG = "#f4f1ea"
    INK = "#2c2825"
    INK_MUTED = "#5c5650"

    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    font_title = load_font(34, hand=True)
    font_lane = load_font(16, hand=True)
    font_name = load_font(18, hand=True)
    font_ports = load_font(12)

    title = "Clawlab — System Internals (component layers)"
    draw.text(((W - font_title.getlength(title)) / 2, MARGIN), title, fill=INK, font=font_title)
    sub = "Open clawlab-system-internals.html for interactive flow tabs"
    draw.text(((W - font_ports.getlength(sub)) / 2, MARGIN + 42), sub, fill=INK_MUTED, font=font_ports)

    y = MARGIN + 72
    for lane in lanes:
        label = lane["label"]
        draw.text(((W - font_lane.getlength(label)) / 2, y), label, fill=INK_MUTED, font=font_lane)
        y += 28
        nodes = lane["nodes"]
        gap = 20
        nw, nh = 200, 88
        total_w = len(nodes) * nw + (len(nodes) - 1) * gap
        x = (W - total_w) // 2
        for node in nodes:
            fill, border = PALETTE[node["kind"]]
            draw.rounded_rectangle((x, y, x + nw, y + nh), radius=12, fill=fill, outline=border, width=2)
            draw.text((x + 10, y + 8), node["name"], fill=INK, font=font_name)
            draw.text((x + 10, y + 32), node["ports"], fill=INK_MUTED, font=font_ports)
            x += nw + gap
        y += nh + 36

    OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT_PNG, format="PNG", optimize=True)
    print(f"Wrote {OUT_PNG}")


def main() -> None:
    OUT_HTML.write_text(render_html(), encoding="utf-8")
    print(f"Wrote {OUT_HTML}")
    render_png_grid()


if __name__ == "__main__":
    main()
