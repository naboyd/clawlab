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


def _request_id(row: dict[str, Any]) -> str:
    """Pairing approve requires requestId — never deviceId."""
    return str(row.get("requestId") or row.get("id") or "").strip()


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


def _filter_pending(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in items or []:
        rid = _request_id(row)
        if not rid:
            continue
        out.append(row)
    return out


def _normalize_device_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, list):
        return {"pending": _filter_pending(_normalize_entries(payload)), "paired": []}
    if not isinstance(payload, dict):
        return {"pending": [], "paired": [], "raw": payload}

    pending = payload.get("pending")
    paired = payload.get("paired")
    if pending is None and paired is None:
        pending = payload.get("pendingRequests") or payload.get("requests")
        paired = payload.get("pairedDevices") or payload.get("devices")
        if pending is None and paired is None and _request_id(payload):
            pending = [payload]

    return {
        "pending": _filter_pending(_normalize_entries(pending)),
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


def _normalize_cli_list(cli_payload: Any) -> dict[str, Any]:
    if isinstance(cli_payload, list):
        return {"pending": _filter_pending(_normalize_entries(cli_payload)), "paired": []}
    if isinstance(cli_payload, dict):
        if "text" in cli_payload and not any(
            k in cli_payload for k in ("pending", "paired", "pendingRequests", "devices")
        ):
            return _cli_parse_list_text(str(cli_payload.get("text", "")))
        return _normalize_device_payload(cli_payload)
    return {"pending": [], "paired": []}


def _list_via_cli() -> dict[str, Any] | None:
    ok, cli_payload = _cli_json(["devices", "list"])
    if not ok:
        return None
    data = _normalize_cli_list(cli_payload)
    data["source"] = "cli"
    return data


def _list_via_http() -> dict[str, Any] | None:
    status, payload = _http_json("GET", "/api/devices")
    if status != 200:
        return None
    data = _normalize_device_payload(payload)
    data["source"] = "http"
    return data


def list_devices() -> dict[str, Any]:
    """Return {pending, paired, source, error?}. Prefers openclaw CLI when available."""
    cli_data = _list_via_cli()
    if cli_data is not None:
        return cli_data

    http_data = _list_via_http()
    if http_data is not None:
        return http_data

    status, payload = _http_json("GET", "/api/devices")
    err_msg = ""
    if isinstance(payload, dict):
        err_msg = str(payload.get("error") or "")
    return {
        "pending": [],
        "paired": [],
        "source": "none",
        "error": err_msg or f"HTTP status {status}; openclaw CLI unavailable",
    }


def _approve_via_http(request_id: str) -> tuple[bool, str]:
    last_status = 0
    last_err = ""
    for body in ({"requestId": request_id}, {"request_id": request_id}):
        status, payload = _http_json("POST", "/api/devices/approve", body=body)
        last_status = status
        if status in (200, 204):
            return True, "http"
        if isinstance(payload, dict):
            last_err = str(payload.get("error") or payload.get("message") or "")
    return False, last_err or f"HTTP approve failed (status {last_status})"


def _approve_via_cli(request_id: str) -> tuple[bool, str]:
    ok, cli_payload = _cli_json(["devices", "approve", request_id])
    if ok:
        return True, "cli"
    if isinstance(cli_payload, dict):
        return False, str(cli_payload.get("error") or "cli approve failed")
    return False, "cli approve failed"


def approve_device(request_id: str) -> dict[str, Any]:
    request_id = (request_id or "").strip()
    if not request_id:
        return {"ok": False, "error": "requestId required"}

    before = list_devices()
    before_ids = {_request_id(p) for p in before.get("pending") or []}

    source = ""
    err_parts: list[str] = []
    http_ok, http_err = _approve_via_http(request_id)
    if http_ok:
        source = "http"
    else:
        err_parts.append(http_err)

    after = list_devices()
    if request_id in {_request_id(p) for p in after.get("pending") or []}:
        ok_cli, cli_err = _approve_via_cli(request_id)
        if ok_cli:
            source = source or "cli"
        elif cli_err:
            err_parts.append(cli_err)
        after = list_devices()

    after_pending = after.get("pending") or []
    after_ids = {_request_id(p) for p in after_pending}

    if request_id in after_ids:
        hint = (
            "Request still pending after approve. Close extra Control UI tabs, "
            "refresh this page, and approve the current requestId (OpenClaw may "
            "issue a new id after reconnect or scope upgrade)."
        )
        return {
            "ok": False,
            "error": err_parts[0] if err_parts else hint,
            "requestId": request_id,
            "source": source or "none",
        }

    result: dict[str, Any] = {
        "ok": True,
        "source": source or "http",
        "requestId": request_id,
    }
    if len(after_pending) > 0:
        new_ids = sorted(after_ids - (before_ids - {request_id}))
        result["warning"] = (
            f"Approved {request_id[:8]}… but {len(after_pending)} pending request(s) remain "
            f"({', '.join(x[:8] + '…' for x in new_ids[:3])}). "
            "Often a scope upgrade or a second browser tab — approve again or close extra tabs."
        )
    return result


def pending_count() -> int:
    data = list_devices()
    return len(data.get("pending") or [])
