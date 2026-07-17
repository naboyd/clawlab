#!/usr/bin/env python3
"""List and approve OpenClaw gateway device pairing (HTTP API with CLI fallback)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

TOKEN_ENV = "OPENCLAW_GATEWAY_TOKEN"
DEFAULT_GATEWAY = "http://127.0.0.1:18789"


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def read_gateway_token() -> str:
    val = os.environ.get(TOKEN_ENV, "").strip()
    if val:
        return val
    oc_home = Path(os.environ.get("OPENCLAW_HOME", Path.home() / ".openclaw")).expanduser()
    for fname in (".env", "gateway.systemd.env"):
        env = _read_env_file(oc_home / fname)
        if env.get(TOKEN_ENV):
            return env[TOKEN_ENV]
    return ""


def gateway_base_url() -> str:
    port = os.environ.get("OPENCLAW_GATEWAY_PORT", "18789").strip() or "18789"
    return os.environ.get("OPENCLAW_GATEWAY_URL", f"http://127.0.0.1:{port}").rstrip("/")


def _http_json(method: str, path: str, *, body: dict | None = None) -> tuple[int, Any]:
    token = read_gateway_token()
    if not token:
        return 0, {"error": f"{TOKEN_ENV} not configured"}

    base = gateway_base_url()
    paths = [path]
    if not path.startswith("/openclaw"):
        paths.append(f"/openclaw{path}")

    last_err = ""
    for p in paths:
        url = f"{base}{p}"
        data = None
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                raw = resp.read().decode()
                if not raw.strip():
                    return resp.status, {}
                return resp.status, json.loads(raw)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode(errors="replace")
            try:
                payload = json.loads(raw) if raw.strip() else {}
            except json.JSONDecodeError:
                payload = {"error": raw or exc.reason}
            return exc.code, payload
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_err = str(exc)
            continue
    return 0, {"error": last_err or "gateway unreachable"}


def _normalize_entries(items: Any) -> list[dict[str, Any]]:
    if not items:
        return []
    if isinstance(items, dict):
        out: list[dict[str, Any]] = []
        for key, val in items.items():
            if isinstance(val, dict):
                row = dict(val)
                row.setdefault("requestId", row.get("id") or key)
                out.append(row)
        return out
    if isinstance(items, list):
        return [x for x in items if isinstance(x, dict)]
    return []


def _normalize_device_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"pending": [], "paired": [], "raw": payload}

    pending = payload.get("pending")
    paired = payload.get("paired")
    if pending is None and paired is None:
        pending = payload.get("pendingRequests") or payload.get("requests")
        paired = payload.get("pairedDevices") or payload.get("devices")

    return {
        "pending": _normalize_entries(pending),
        "paired": _normalize_entries(paired),
    }


def _cli_json(args: list[str]) -> tuple[bool, Any]:
    token = read_gateway_token()
    if not token:
        return False, {"error": f"{TOKEN_ENV} not configured"}
    openclaw = shutil.which("openclaw")
    if not openclaw:
        return False, {"error": "openclaw CLI not on PATH"}

    cmd = [openclaw, *args, "--json", "--token", token]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return False, {"error": str(exc)}

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "openclaw command failed").strip()
        return False, {"error": err}

    out = (proc.stdout or "").strip()
    if not out:
        return True, {}
    try:
        return True, json.loads(out)
    except json.JSONDecodeError:
        return True, {"text": out}


def _cli_parse_list_text(text: str) -> dict[str, Any]:
    pending: list[dict[str, Any]] = []
    paired: list[dict[str, Any]] = []
    section = ""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        lower = line.lower()
        if "pending" in lower and "request" in lower:
            section = "pending"
            continue
        if "paired" in lower and "device" in lower:
            section = "paired"
            continue
        m = re.search(r"([0-9a-f-]{8,})", line, re.I)
        if not m:
            continue
        rid = m.group(1)
        row = {"requestId": rid, "summary": line}
        if section == "paired":
            paired.append(row)
        else:
            pending.append(row)
    return {"pending": pending, "paired": paired}


def list_devices() -> dict[str, Any]:
    """Return {pending, paired, source, error?}."""
    status, payload = _http_json("GET", "/api/devices")
    if status == 200:
        data = _normalize_device_payload(payload)
        data["source"] = "http"
        return data

    ok, cli_payload = _cli_json(["devices", "list"])
    if ok:
        if isinstance(cli_payload, dict):
            data = _normalize_device_payload(cli_payload)
        else:
            data = _cli_parse_list_text(str(cli_payload.get("text", "")))
        data["source"] = "cli"
        if status and status != 200:
            data["http_note"] = f"HTTP /api/devices returned {status}"
        return data

    return {
        "pending": [],
        "paired": [],
        "source": "none",
        "error": (cli_payload or {}).get("error")
        or (payload or {}).get("error")
        or f"HTTP status {status}",
    }


def approve_device(request_id: str) -> dict[str, Any]:
    request_id = (request_id or "").strip()
    if not request_id:
        return {"ok": False, "error": "requestId required"}

    status, payload = _http_json(
        "POST",
        "/api/devices/approve",
        body={"requestId": request_id},
    )
    if status in (200, 204):
        return {"ok": True, "source": "http", "requestId": request_id}

    ok, cli_payload = _cli_json(["devices", "approve", request_id])
    if ok:
        return {"ok": True, "source": "cli", "requestId": request_id}

    err = ""
    if isinstance(payload, dict):
        err = str(payload.get("error") or payload.get("message") or "")
    if not err and isinstance(cli_payload, dict):
        err = str(cli_payload.get("error") or "")
    return {"ok": False, "error": err or f"approve failed (HTTP {status})"}


def pending_count() -> int:
    data = list_devices()
    return len(data.get("pending") or [])
