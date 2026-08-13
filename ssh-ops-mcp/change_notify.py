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


def _changes_portal_url() -> str:
    """Link to MCP Admin → Changes tab (from portal config.env)."""
    base = (os.environ.get("CLAW_PORTAL_SSH_OPS_URL") or "").strip()
    if not base:
        hub = (os.environ.get("CLAW_PORTAL_HUB_URL") or "").strip()
        path = (os.environ.get("CLAW_PORTAL_SSH_OPS_PATH") or "/ssh-ops/").strip()
        if hub:
            base = f"{hub.rstrip('/')}/{path.strip('/')}/"
    if not base:
        return ""
    return f"{base.rstrip('/')}/?tab=changes"


def _change_host(change: dict[str, Any]) -> str:
    targets = change.get("targets") or []
    if targets and isinstance(targets[0], dict):
        return str(targets[0].get("name") or "—")
    return "—"


def _change_lines_preview(change: dict[str, Any], *, limit: int = 8) -> str:
    lines_preview: list[str] = []
    targets = change.get("targets") or []
    if targets and isinstance(targets[0], dict):
        for line in (targets[0].get("apply") or [])[:limit]:
            text = str(line)
            if " secret " in text:
                head, _ = text.split(" secret ", 1)
                lines_preview.append(f"{head} secret ***")
            else:
                lines_preview.append(text)
    return "\n".join(f"  `{ln}`" for ln in lines_preview) or "  —"


def _dispatch_change_webhooks(markdown: str, *, log_tag: str, change_id: str) -> dict[str, Any]:
    if os.environ.get("SSH_OPS_NOTIFY_CHANGES", "1").lower() in ("0", "false", "no", "off"):
        return {"skipped": True, "reason": "SSH_OPS_NOTIFY_CHANGES disabled"}

    webhooks = _load_webhooks()
    if not webhooks:
        return {
            "skipped": True,
            "reason": "No Webex webhook with events including 'change' in DefenseClaw config",
        }

    results = []
    for wh in webhooks:
        ok, info = _post_webex(wh, markdown)
        results.append({"webhook": wh["name"], "ok": ok, "detail": info})
        log.info("change_notify %s %s -> %s %s", log_tag, change_id, wh["name"], info)

    return {"notified": True, "results": results}


def notify_change_proposed(change: dict[str, Any]) -> dict[str, Any]:
    """Post Webex alert when a change awaits four-eyes approval (non-fatal on failure)."""
    try:
        import webex_approval

        ok, detail = webex_approval.post_proposed_notification(change)
        if ok:
            return {"notified": True, "results": [{"webhook": "webex", "ok": True, "detail": detail}]}
        return {"skipped": True, "reason": detail}
    except Exception as exc:  # noqa: BLE001
        log.warning("webex proposed notification failed: %s", exc)

    cid = change.get("id", "—")
    portal = _changes_portal_url()
    portal_line = f"- **Approve in:** [MCP Admin Changes]({portal})\n" if portal else ""

    md = "\n".join([
        f"👀 **IOS change needs approval (four-eyes)** on **{HOSTID}**",
        f"- **Change:** `{cid}`",
        f"- **Host:** `{_change_host(change)}`",
        f"- **Proposed by:** `{change.get('created_by') or '—'}`",
        f"- **Type:** {change.get('change_type', '—')}",
        f"- **Risk:** {change.get('risk', '—')}",
        f"- **Group:** {change.get('policy_group') or '—'} ({change.get('group_access') or 'approve'})",
        f"- **Intent:** {change.get('intent') or '—'}",
        f"- **Lines:**\n{_change_lines_preview(change)}",
        portal_line.rstrip(),
        "- **Note:** approver must be a **different** claw-auth user than the proposer.",
    ]).strip()

    return _dispatch_change_webhooks(md, log_tag="proposed", change_id=str(cid))


def notify_change_approved(change: dict[str, Any], *, approver: str) -> dict[str, Any]:
    """Post Webex when a change is approved and ready to apply."""
    cid = change.get("id", "—")
    portal = _changes_portal_url()
    portal_line = f"- **Apply in:** [MCP Admin Changes]({portal})\n" if portal else ""

    md = "\n".join([
        f"✅ **IOS change approved** on **{HOSTID}**",
        f"- **Change:** `{cid}`",
        f"- **Host:** `{_change_host(change)}`",
        f"- **Proposed by:** `{change.get('created_by') or '—'}`",
        f"- **Approved by:** `{approver}`",
        f"- **Risk:** {change.get('risk', '—')}",
        f"- **Intent:** {change.get('intent') or '—'}",
        portal_line.rstrip(),
    ]).strip()

    return _dispatch_change_webhooks(md, log_tag="approved", change_id=str(cid))


def notify_change_rejected(change: dict[str, Any], *, actor: str) -> dict[str, Any]:
    """Post Webex when a change is rejected."""
    cid = change.get("id", "—")
    md = "\n".join([
        f"❌ **IOS change rejected** on **{HOSTID}**",
        f"- **Change:** `{cid}`",
        f"- **Host:** `{_change_host(change)}`",
        f"- **Proposed by:** `{change.get('created_by') or '—'}`",
        f"- **Rejected by:** `{actor}`",
        f"- **Intent:** {change.get('intent') or '—'}",
    ])
    return _dispatch_change_webhooks(md, log_tag="rejected", change_id=str(cid))


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
    cid = change.get("id", "—")
    md = "\n".join([
        f"✅ **IOS config applied** on **{HOSTID}**",
        f"- **Change:** `{cid}`",
        f"- **Host:** `{_change_host(change)}`",
        f"- **Type:** {change.get('change_type', '—')}",
        f"- **Risk:** {change.get('risk', '—')}",
        f"- **Group:** {change.get('policy_group') or '—'}",
        f"- **Actor:** {actor}",
        f"- **Intent:** {change.get('intent') or '—'}",
        f"- **Lines:**\n{_change_lines_preview(change)}",
    ])
    return _dispatch_change_webhooks(md, log_tag="applied", change_id=str(cid))


def notify_self_approval_blocked(
    change: dict[str, Any],
    *,
    approver: str,
    detail: str,
) -> dict[str, Any]:
    """Alert when four-eyes blocks a self-approval attempt (non-fatal on failure)."""
    cid = change.get("id", "—")
    md = "\n".join([
        f"🚫 **Self-approval blocked (four-eyes)** on **{HOSTID}**",
        f"- **Change:** `{cid}`",
        f"- **Proposed by:** `{change.get('created_by') or '—'}`",
        f"- **Blocked approver:** `{approver}`",
        f"- **Host:** `{_change_host(change)}`",
        f"- **Risk:** {change.get('risk', '—')}",
        f"- **Intent:** {change.get('intent') or '—'}",
        f"- **Detail:** {detail}",
    ])
    return _dispatch_change_webhooks(md, log_tag="self_approval_blocked", change_id=str(cid))
