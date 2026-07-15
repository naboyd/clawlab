"""Notify operators when approved IOS config changes are applied."""

from __future__ import annotations

import json
import logging
import os
import socket
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger("ssh_ops.notify")

DC_HOME = Path(os.environ.get("DEFENSECLAW_HOME", os.path.expanduser("~/.defenseclaw"))).expanduser()
HOSTID = os.environ.get("SSH_OPS_NOTIFY_HOST") or socket.gethostname()


def _load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.is_file():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _load_webhooks() -> list[dict[str, Any]]:
    cfg_path = DC_HOME / "config.yaml"
    if not cfg_path.is_file():
        return []
    try:
        cfg = yaml.safe_load(cfg_path.read_text()) or {}
    except Exception:
        return []
    env = _load_env(DC_HOME / ".env")
    out: list[dict[str, Any]] = []
    for wh in cfg.get("webhooks") or []:
        if not isinstance(wh, dict):
            continue
        if (wh.get("type") or "").lower() != "webex":
            continue
        if wh.get("enabled") is False:
            continue
        secret_env = wh.get("secret_env") or ""
        token = env.get(secret_env) or os.environ.get(secret_env, "")
        if not token or not wh.get("room_id"):
            continue
        events = set(wh.get("events") or ["block", "drift", "guardrail"])
        if "change" not in events:
            continue
        out.append({
            "name": wh.get("name", "webex"),
            "url": wh.get("url", "https://webexapis.com/v1/messages"),
            "room_id": wh["room_id"],
            "token": token,
        })
    return out


def _post_webex(wh: dict[str, Any], markdown: str) -> tuple[bool, str]:
    body = json.dumps({"roomId": wh["room_id"], "markdown": markdown}).encode()
    req = urllib.request.Request(
        wh["url"],
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {wh['token']}",
            "Content-Type": "application/json",
            "User-Agent": "ssh-ops-change-notify/1.0",
        },
    )
    timeout = float(os.environ.get("SSH_OPS_NOTIFY_TIMEOUT", "10"))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300, f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}: {exc.read()[:200].decode('utf-8', 'replace')}"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def notify_change_applied(change: dict[str, Any], *, actor: str) -> dict[str, Any]:
    """Post Webex alert for a successfully applied change (non-fatal on failure)."""
    if os.environ.get("SSH_OPS_NOTIFY_CHANGES", "1").lower() in ("0", "false", "no", "off"):
        return {"skipped": True, "reason": "SSH_OPS_NOTIFY_CHANGES disabled"}

    webhooks = _load_webhooks()
    if not webhooks:
        return {
            "skipped": True,
            "reason": "No Webex webhook with events including 'change' in DefenseClaw config",
        }

    cid = change.get("id", "—")
    host = "—"
    targets = change.get("targets") or []
    if targets and isinstance(targets[0], dict):
        host = targets[0].get("name") or host

    lines_preview = []
    if targets and isinstance(targets[0], dict):
        for line in (targets[0].get("apply") or [])[:8]:
            if " secret " in str(line):
                head, _ = str(line).split(" secret ", 1)
                lines_preview.append(f"{head} secret ***")
            else:
                lines_preview.append(str(line))
    preview = "\n".join(f"  `{ln}`" for ln in lines_preview) or "  —"

    md = "\n".join([
        f"✅ **IOS config applied** on **{HOSTID}**",
        f"- **Change:** `{cid}`",
        f"- **Host:** `{host}`",
        f"- **Type:** {change.get('change_type', '—')}",
        f"- **Risk:** {change.get('risk', '—')}",
        f"- **Group:** {change.get('policy_group') or '—'}",
        f"- **Actor:** {actor}",
        f"- **Intent:** {change.get('intent') or '—'}",
        f"- **Lines:**\n{preview}",
    ])

    results = []
    for wh in webhooks:
        ok, info = _post_webex(wh, md)
        results.append({"webhook": wh["name"], "ok": ok, "detail": info})
        log.info("change_notify %s -> %s %s", cid, wh["name"], info)

    return {"notified": True, "results": results}


def notify_self_approval_blocked(
    change: dict[str, Any],
    *,
    approver: str,
    detail: str,
) -> dict[str, Any]:
    """Alert when four-eyes blocks a self-approval attempt (non-fatal on failure)."""
    if os.environ.get("SSH_OPS_NOTIFY_CHANGES", "1").lower() in ("0", "false", "no", "off"):
        return {"skipped": True, "reason": "SSH_OPS_NOTIFY_CHANGES disabled"}

    webhooks = _load_webhooks()
    if not webhooks:
        return {"skipped": True, "reason": "No Webex webhook with events including 'change'"}

    cid = change.get("id", "—")
    md = "\n".join([
        f"🚫 **Self-approval blocked (four-eyes)** on **{HOSTID}**",
        f"- **Change:** `{cid}`",
        f"- **Proposed by:** `{change.get('created_by') or '—'}`",
        f"- **Blocked approver:** `{approver}`",
        f"- **Host:** `{(change.get('targets') or [{}])[0].get('name', '—') if change.get('targets') else '—'}`",
        f"- **Risk:** {change.get('risk', '—')}",
        f"- **Intent:** {change.get('intent') or '—'}",
        f"- **Detail:** {detail}",
    ])

    results = []
    for wh in webhooks:
        ok, info = _post_webex(wh, md)
        results.append({"webhook": wh["name"], "ok": ok, "detail": info})
        log.info("change_notify self_approval_blocked %s -> %s %s", cid, wh["name"], info)

    return {"notified": True, "results": results}
