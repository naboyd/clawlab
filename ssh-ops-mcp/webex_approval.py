"""Webex adaptive-card approval for four-eyes change workflow."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger("ssh_ops.webex_approval")

DC_HOME = Path(os.environ.get("DEFENSECLAW_HOME", os.path.expanduser("~/.defenseclaw"))).expanduser()
_CHANGE_ID_RE = re.compile(r"^chg-[0-9]{8}-[0-9]{4,}$")
_USED_TOKENS_PATH = Path(
    os.environ.get(
        "WEBEX_ACTION_TOKENS_FILE",
        "/data/webex-action-tokens.json" if Path("/data").is_dir() else "./webex-action-tokens.json",
    )
).expanduser()


def _action_secret() -> bytes:
    for key in ("WEBEX_ACTION_SECRET", "CLAWLAB_INTERNAL_TOKEN"):
        val = (os.environ.get(key) or "").strip()
        if val:
            return val.encode()
    env_path = DC_HOME / ".env"
    if env_path.is_file():
        for line in env_path.read_text().splitlines():
            if line.strip().startswith("CLAWLAB_INTERNAL_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'").encode()
    return b"clawlab-webex-action-dev-only"


def webhook_secret() -> str:
    return (os.environ.get("WEBEX_APPROVAL_WEBHOOK_SECRET") or "").strip()


def cards_enabled() -> bool:
    return os.environ.get("WEBEX_APPROVAL_CARDS", "1").lower() not in ("0", "false", "no", "off")


def public_hook_url() -> str:
    explicit = (os.environ.get("WEBEX_APPROVAL_PUBLIC_URL") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    base = (os.environ.get("CLAW_PORTAL_SSH_OPS_URL") or "").strip().rstrip("/")
    if base:
        return f"{base}/webex/hooks/attachment-actions"
    return ""


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


def _webex_token() -> str:
    env = _load_env(DC_HOME / ".env")
    for key in ("DEFENSECLAW_WEBEX_TOKEN",):
        val = env.get(key) or os.environ.get(key, "")
        if val:
            return val
    return ""


def _load_webhook() -> dict[str, Any] | None:
    cfg_path = DC_HOME / "config.yaml"
    if not cfg_path.is_file():
        return None
    try:
        cfg = yaml.safe_load(cfg_path.read_text()) or {}
    except Exception:
        return None
    env = _load_env(DC_HOME / ".env")
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
        return {
            "name": wh.get("name", "webex"),
            "url": wh.get("url", "https://webexapis.com/v1/messages"),
            "room_id": wh["room_id"],
            "token": token,
        }
    return None


def verify_webhook_signature(body: bytes, signature_header: str | None) -> bool:
    secret = webhook_secret()
    if not secret:
        log.warning("WEBEX_APPROVAL_WEBHOOK_SECRET not set — skipping signature check")
        return True
    if not signature_header:
        return False
    sig = signature_header.strip()
    if sig.startswith("sha1="):
        sig = sig[5:]
    expected = hmac.new(secret.encode(), body, hashlib.sha1).hexdigest()
    return hmac.compare_digest(expected, sig)


def _portal_changes_url(change_id: str | None = None) -> str:
    base = (os.environ.get("CLAW_PORTAL_SSH_OPS_URL") or "").strip()
    if not base:
        hub = (os.environ.get("CLAW_PORTAL_HUB_URL") or "").strip()
        path = (os.environ.get("CLAW_PORTAL_SSH_OPS_PATH") or "/ssh-ops/").strip()
        if hub:
            base = f"{hub.rstrip('/')}/{path.strip('/')}/"
    if not base:
        return ""
    url = f"{base.rstrip('/')}/?tab=changes"
    if change_id:
        url += f"&change={change_id}"
    return url


def mint_action_token(change_id: str, action: str, *, ttl_seconds: int | None = None) -> str:
    if not _CHANGE_ID_RE.match(change_id):
        raise ValueError(f"invalid change id: {change_id}")
    if action not in ("approve", "reject"):
        raise ValueError(f"invalid action: {action}")
    ttl = ttl_seconds or int(os.environ.get("WEBEX_ACTION_TOKEN_TTL", str(86400)))
    exp = int(time.time()) + max(300, ttl)
    payload = f"{change_id}:{action}:{exp}"
    sig = hmac.new(_action_secret(), payload.encode(), hashlib.sha256).hexdigest()
    raw = f"{payload}:{sig}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _load_used_tokens() -> set[str]:
    if not _USED_TOKENS_PATH.is_file():
        return set()
    try:
        data = json.loads(_USED_TOKENS_PATH.read_text())
        return set(data if isinstance(data, list) else [])
    except Exception:
        return set()


def _mark_token_used(token: str) -> None:
    used = _load_used_tokens()
    used.add(token)
    _USED_TOKENS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _USED_TOKENS_PATH.write_text(json.dumps(sorted(used)[-500:]))


def verify_action_token(token: str) -> tuple[str, str] | None:
    if not token:
        return None
    try:
        pad = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(token + pad).decode()
    except Exception:
        return None
    parts = raw.rsplit(":", 1)
    if len(parts) != 2:
        return None
    payload, sig = parts
    expected = hmac.new(_action_secret(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    change_id, action, exp_s = payload.split(":", 2)
    if action not in ("approve", "reject"):
        return None
    if not _CHANGE_ID_RE.match(change_id):
        return None
    if int(exp_s) < int(time.time()):
        return None
    if token in _load_used_tokens():
        return None
    return change_id, action


def action_link(change_id: str, action: str) -> str:
    base = (os.environ.get("CLAW_PORTAL_SSH_OPS_URL") or "").strip().rstrip("/")
    if not base:
        return _portal_changes_url(change_id)
    token = mint_action_token(change_id, action)
    return f"{base}/webex/action?token={token}"


def build_proposed_card(change: dict[str, Any]) -> dict[str, Any]:
    cid = change.get("id", "—")
    host = "—"
    targets = change.get("targets") or []
    if targets and isinstance(targets[0], dict):
        host = targets[0].get("name") or host
    body_lines = [
        {"type": "TextBlock", "text": "IOS change needs approval (four-eyes)", "weight": "Bolder", "size": "Medium"},
        {"type": "FactSet", "facts": [
            {"title": "Change", "value": str(cid)},
            {"title": "Host", "value": str(host)},
            {"title": "Proposed by", "value": str(change.get("created_by") or "—")},
            {"title": "Risk", "value": str(change.get("risk") or "—")},
            {"title": "Intent", "value": str(change.get("intent") or change.get("change_type") or "—")},
        ]},
        {"type": "TextBlock", "text": "Approver must be a **different** claw-auth user (Webex email linked in claw-auth).", "wrap": True, "isSubtle": True},
    ]
    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.2",
        "body": body_lines,
        "actions": [
            {
                "type": "Action.Submit",
                "title": "Approve",
                "style": "positive",
                "data": {"clawlab_action": "approve", "change_id": cid},
            },
            {
                "type": "Action.Submit",
                "title": "Reject",
                "style": "destructive",
                "data": {"clawlab_action": "reject", "change_id": cid},
            },
        ],
    }


def post_room_message(
    *,
    markdown: str,
    attachments: list[dict[str, Any]] | None = None,
    room_id: str | None = None,
) -> tuple[bool, str]:
    wh = _load_webhook()
    if not wh:
        return False, "no webex webhook"
    body: dict[str, Any] = {
        "roomId": room_id or wh["room_id"],
        "markdown": markdown,
    }
    if attachments:
        body["attachments"] = attachments
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        wh["url"],
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {wh['token']}",
            "Content-Type": "application/json",
            "User-Agent": "ssh-ops-webex-approval/1.0",
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


def post_proposed_notification(change: dict[str, Any]) -> tuple[bool, str]:
    cid = change.get("id", "—")
    portal = _portal_changes_url(str(cid))
    approve_link = action_link(str(cid), "approve")
    reject_link = action_link(str(cid), "reject")
    host = "—"
    targets = change.get("targets") or []
    if targets and isinstance(targets[0], dict):
        host = str(targets[0].get("name") or "—")
    md_lines = [
        f"👀 **IOS change needs approval (four-eyes)** — `{cid}`",
        f"- **Host:** `{host}`",
        f"- **Proposed by:** `{change.get('created_by') or '—'}`",
        f"- **Portal:** [MCP Admin Changes]({portal})" if portal else "",
        f"- **Fallback:** [Approve in browser]({approve_link}) · [Reject]({reject_link})",
    ]
    markdown = "\n".join(line for line in md_lines if line)
    attachments = None
    if cards_enabled():
        attachments = [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": build_proposed_card(change),
        }]
    return post_room_message(markdown=markdown, attachments=attachments)


def _extract_action_fields(payload: dict[str, Any]) -> tuple[str, str, str, str]:
    """Return (change_id, action, person_email, room_id)."""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    inputs = data.get("inputs") if isinstance(data.get("inputs"), dict) else {}
    action_data = data.get("data") if isinstance(data.get("data"), dict) else {}
    merged = {**action_data, **inputs}
    change_id = str(merged.get("change_id") or "").strip()
    action = str(merged.get("clawlab_action") or merged.get("action") or "").strip().lower()
    person_email = str(
        data.get("personEmail") or payload.get("personEmail") or merged.get("personEmail") or ""
    ).strip().lower()
    room_id = str(data.get("roomId") or payload.get("roomId") or "").strip()
    return change_id, action, person_email, room_id


def handle_attachment_action(payload: dict[str, Any]) -> dict[str, Any]:
    """Process Webex attachmentActions webhook; approve/reject via linked email."""
    import change_engine
    from claw_user_lookup import lookup_username_by_webex_email

    change_id, action, person_email, room_id = _extract_action_fields(payload)
    if action not in ("approve", "reject"):
        return {"ok": False, "error": f"unknown action: {action or '—'}"}
    if not change_id:
        return {"ok": False, "error": "missing change_id"}

    username = lookup_username_by_webex_email(person_email)
    if not username:
        msg = (
            f"Webex user `{person_email or 'unknown'}` is not linked to claw-auth. "
            "An admin must set **Webex email** on the user in claw-auth → Users."
        )
        post_room_message(markdown=f"🚫 **Approval blocked** — {msg}", room_id=room_id or None)
        return {"ok": False, "error": "webex_email_not_linked", "detail": msg}

    if action == "approve":
        result = change_engine.approve_change(change_id, approver=username, note="via Webex card")
    else:
        result = change_engine.reject_change(change_id, approver=username, note="via Webex card")

    if result.get("error"):
        post_room_message(
            markdown=f"🚫 **{action.title()} blocked** for `{change_id}` — {result['error']}",
            room_id=room_id or None,
        )
        return {"ok": False, "error": result["error"], "code": result.get("code")}

    post_room_message(
        markdown=f"✅ **Change `{change_id}` {action}d** by `{username}` (Webex: {person_email}).",
        room_id=room_id or None,
    )
    return {"ok": True, "change_id": change_id, "action": action, "user": username}


def handle_webhook_request(body: bytes) -> tuple[dict[str, Any], int]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        return {"ok": False, "error": "invalid json"}, 400

    if not isinstance(payload, dict):
        return {"ok": False, "error": "expected object"}, 400

    # Webex webhook validation handshake (on webhook create)
    if payload.get("secret") and payload.get("name") and not payload.get("resource"):
        return payload, 200

    resource = str(payload.get("resource") or "").lower()
    event = str(payload.get("event") or "").lower()
    if resource == "attachmentactions" and event == "created":
        inner = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        result = handle_attachment_action(inner)
        return result, 200 if result.get("ok") else 422

    return {"ok": True, "ignored": True, "resource": resource, "event": event}, 200
