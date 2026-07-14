#!/usr/bin/env python3
"""
dc-webex-bridge — DefenseClaw audit -> Webex alert bridge.

Why this exists
---------------
In DefenseClaw 0.8.4 the OpenClaw enforcement lanes that actually catch things
(subprocess shims + tool-call inspection) log `would_block=false` and are
treated as advisory, so they never reach the built-in runtime webhook
dispatcher. The only lane that natively dispatches Webex ("guardrail" events)
is the prompt-lane LLM judge, which on a local quantized model is unreliable.

This bridge closes that gap deterministically: it tails the DefenseClaw audit
database (the source of truth that the *reliable* pattern engine writes to) and
posts a Webex message for every HIGH/CRITICAL violation. No LLM, no API cost,
fully local. It reuses the EXISTING webhook config (url / room_id / token /
min_severity / events) from ~/.defenseclaw/config.yaml + ~/.defenseclaw/.env, so
rotating the Webex token or room in DefenseClaw keeps working with no changes.

It is intentionally read-only against DefenseClaw state (opens audit.db ro) and
keeps its own cursor/state file, so it can never interfere with the gateway.
"""
from __future__ import annotations
import argparse, json, os, re, socket, sqlite3, sys, time, urllib.request, urllib.error, html
from pathlib import Path

HOSTID = os.environ.get("DC_BRIDGE_HOST") or socket.gethostname()

DC_HOME = Path(os.environ.get("DEFENSECLAW_HOME", os.path.expanduser("~/.defenseclaw")))
CONFIG  = DC_HOME / "config.yaml"
ENVFILE = DC_HOME / ".env"
AUDITDB = DC_HOME / "audit.db"
STATE   = DC_HOME / "webex-bridge.state"

SEV_RANK = {"": 0, "NONE": 0, "INFO": 1, "LOW": 2, "MEDIUM": 3, "HIGH": 4, "CRITICAL": 5}

SEV_RE = re.compile(r'severity[=:]\s*"?(CRITICAL|HIGH|MEDIUM|LOW|INFO|NONE)"?', re.I)

def effective_severity(row) -> str:
    col = (row["severity"] or "").upper()
    best, best_rank = (col or "NONE"), SEV_RANK.get(col, 0)
    m = SEV_RE.search(row["details"] or "")
    if m and SEV_RANK.get(m.group(1).upper(), 0) > best_rank:
        best = m.group(1).upper()
    return best

# audit `action` -> logical webhook event category. Only actions that represent
# a genuine security violation/detection are mapped; telemetry maps to None.
def categorize(action: str, details: str) -> str | None:
    a = (action or "").lower()
    d = (details or "").lower()
    if a in ("inspect-tool-block", "tool-block", "block") or a.endswith("-block"):
        return "block"
    if a.startswith("guardrail"):
        return "guardrail"
    if a == "llm-judge-response":
        # only the meaningful judge verdicts, not benign/telemetry rows
        if any(k in d for k in ("injection", "exfil", "action=block", "jailbreak", "pii")):
            return "guardrail"
        return None
    if a == "drift":
        return "drift"
    if a == "scan":
        return "scan"
    if a.startswith("network") and ("block" in d or "deny" in d):
        return "block"
    return None

# Actors that represent the operator / DefenseClaw itself. Config edits by these
# actors produce drift/config events we do NOT want to page on.
OPERATOR_ACTORS = {"cli:operator", "operator", "defenseclaw", "defenseclaw-cli",
                   "defenseclaw-gateway", "cli"}

def load_env(path: Path) -> dict:
    env = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env

def load_webhooks() -> list[dict]:
    import yaml
    cfg = yaml.safe_load(CONFIG.read_text()) or {}
    env = load_env(ENVFILE)
    out = []
    for wh in (cfg.get("webhooks") or []):
        if (wh.get("type") or "").lower() != "webex":
            continue
        if wh.get("enabled") is False:
            continue
        token = env.get(wh.get("secret_env", ""), "") or os.environ.get(wh.get("secret_env", ""), "")
        if not token or not wh.get("room_id"):
            continue
        out.append({
            "name": wh.get("name", "webex"),
            "url": wh.get("url", "https://webexapis.com/v1/messages"),
            "room_id": wh["room_id"],
            "token": token,
            "min_severity": (wh.get("min_severity") or "HIGH").upper(),
            "events": set(wh.get("events") or ["block", "drift", "guardrail"]),
        })
    return out

def load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text())
        except Exception:
            pass
    return {"last_rowid": 0, "seen": []}

def save_state(st: dict):
    st["seen"] = st.get("seen", [])[-500:]
    tmp = STATE.with_suffix(".state.tmp")
    tmp.write_text(json.dumps(st))
    tmp.replace(STATE)

def audit_conn() -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{AUDITDB}?mode=ro", uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA query_only=ON")
    c.execute("PRAGMA busy_timeout=5000")
    return c

def max_rowid() -> int:
    with audit_conn() as c:
        r = c.execute("SELECT COALESCE(MAX(rowid),0) FROM audit_events").fetchone()
        return int(r[0])

def fetch_new(last_rowid: int) -> list[sqlite3.Row]:
    with audit_conn() as c:
        return c.execute(
            "SELECT rowid, id, timestamp, action, target, actor, details, severity, "
            "connector, tool_name, enforced FROM audit_events "
            "WHERE rowid > ? ORDER BY rowid ASC LIMIT 500", (last_rowid,)
        ).fetchall()

def is_violation(row: sqlite3.Row, wh: dict) -> str | None:
    sev = effective_severity(row)
    cat = categorize(row["action"], row["details"] or "")
    if cat is None:
        return None
    if cat != "block" and SEV_RANK.get(sev, 0) < SEV_RANK.get(wh["min_severity"], 4):
        return None
    if cat == "scan":
        if sev != "CRITICAL":
            return None
    elif cat not in wh["events"]:
        return None
    if cat == "drift" and (row["actor"] or "").lower() in OPERATOR_ACTORS:
        return None
    return cat

SEV_EMOJI = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵"}

def format_markdown(row: sqlite3.Row, cat: str) -> str:
    sev = effective_severity(row) or "NONE"
    emoji = SEV_EMOJI.get(sev, "⚪")
    details = (row["details"] or "").strip()
    if len(details) > 400:
        details = details[:400] + "…"
    target = row["target"] or row["tool_name"] or "—"
    lines = [
        f"{emoji} **DefenseClaw {cat.upper()}** on **{HOSTID}** — `{row['action']}` ({sev})",
        f"- **Host:** `{HOSTID}`",
        f"- **Actor:** {row['actor'] or '—'}",
        f"- **Target:** `{target}`",
    ]
    if row["connector"]:
        lines.append(f"- **Connector:** {row['connector']}")
    if row["tool_name"] and row["tool_name"] != target:
        lines.append(f"- **Tool:** `{row['tool_name']}`")
    if details:
        lines.append(f"- **Details:** {details}")
    lines.append(f"- **Enforced:** {'yes' if row['enforced'] else 'advisory (detect-only)'}")
    lines.append(f"- **Time:** {row['timestamp']}")
    lines.append(f"- **Event:** `{row['id']}`")
    return "\n".join(lines)

def post_webex(wh: dict, markdown: str, timeout: float = 10.0) -> tuple[bool, str]:
    body = json.dumps({"roomId": wh["room_id"], "markdown": markdown}).encode()
    req = urllib.request.Request(
        wh["url"], data=body, method="POST",
        headers={"Authorization": f"Bearer {wh['token']}", "Content-Type": "application/json",
                 "User-Agent": "dc-webex-bridge/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return (200 <= r.status < 300), f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        retry = e.headers.get("Retry-After")
        return False, f"HTTP {e.code}{' retry-after=' + retry if retry else ''}: {e.read()[:200].decode('utf-8','replace')}"
    except Exception as e:
        return False, f"ERR {e}"

def log(msg: str):
    print(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg}", flush=True)

def run_loop(poll: float, dedup_window: int):
    webhooks = load_webhooks()
    if not webhooks:
        log("FATAL: no enabled Webex webhook found in config.yaml (need type=webex, room_id, secret_env token)")
        sys.exit(2)
    log(f"started: {len(webhooks)} webex endpoint(s); poll={poll}s")
    st = load_state()
    if not st.get("last_rowid"):
        st["last_rowid"] = max_rowid()
        save_state(st)
        log(f"initialized cursor at rowid={st['last_rowid']} (no historical replay)")
    recent = {}
    while True:
        try:
            rows = fetch_new(st["last_rowid"])
            for row in rows:
                st["last_rowid"] = row["rowid"]
                if row["id"] in st["seen"]:
                    continue
                for wh in webhooks:
                    cat = is_violation(row, wh)
                    if not cat:
                        continue
                    key = (row["action"], row["target"], row["severity"])
                    now = time.time()
                    if key in recent and now - recent[key] < dedup_window:
                        log(f"coalesced dup {key}")
                        continue
                    recent[key] = now
                    ok, info = post_webex(wh, format_markdown(row, cat))
                    log(f"dispatch [{wh['name']}] {cat}/{row['action']}/{row['severity']} id={row['id']} -> {'OK' if ok else 'FAIL'} {info}")
                st["seen"].append(row["id"])
            save_state(st)
        except Exception as e:
            log(f"loop error: {e}")
        time.sleep(poll)

def main():
    ap = argparse.ArgumentParser(description="DefenseClaw audit -> Webex bridge")
    ap.add_argument("--poll", type=float, default=float(os.environ.get("DC_BRIDGE_POLL", "5")))
    ap.add_argument("--dedup-window", type=int, default=int(os.environ.get("DC_BRIDGE_DEDUP", "60")))
    ap.add_argument("--test", action="store_true", help="send one synthetic alert to each webhook and exit")
    ap.add_argument("--backfill", type=int, default=0, help="on start, also consider the last N audit rows")
    args = ap.parse_args()

    if args.test:
        for wh in load_webhooks():
            md = f"🧪 **DefenseClaw bridge test** on **{HOSTID}** — if you see this, audit→Webex alerting is live."
            ok, info = post_webex(wh, md)
            log(f"test [{wh['name']}] -> {'OK' if ok else 'FAIL'} {info}")
        return
    if args.backfill:
        st = load_state()
        st["last_rowid"] = max(0, max_rowid() - args.backfill)
        save_state(st)
        log(f"backfill: cursor moved back to rowid={st['last_rowid']}")
    run_loop(args.poll, args.dedup_window)

if __name__ == "__main__":
    main()
