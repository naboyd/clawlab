"""Push ios-xe-policy.yaml into DefenseClaw rule pack and reload sidecars."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import ios_xe_policy


class PolicyReloadError(RuntimeError):
    pass


def _reload_url() -> str:
    explicit = os.environ.get("DEFENSECLAW_POLICY_RELOAD_URL", "").strip()
    if explicit:
        return explicit
    base = os.environ.get(
        "DEFENSECLAW_WEBGUI_URL", "http://host.containers.internal:8770"
    ).rstrip("/")
    return f"{base}/api/policy/reload-enforcement"


def _call_defenseclaw_api(*, reload_openclaw: bool) -> tuple[bool, str]:
    token = os.environ.get("CLAWLAB_INTERNAL_TOKEN", "").strip()
    if not token:
        return False, "CLAWLAB_INTERNAL_TOKEN not set (cannot call DefenseClaw API)."

    url = _reload_url()
    body = json.dumps({"reload_openclaw": reload_openclaw}).encode()
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Clawlab-Internal-Token": token,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            payload = json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        return False, f"DefenseClaw API HTTP {exc.code}: {detail or exc.reason}"
    except urllib.error.URLError as exc:
        return False, f"DefenseClaw API unreachable at {url}: {exc.reason}"
    except json.JSONDecodeError as exc:
        return False, f"DefenseClaw API returned invalid JSON: {exc}"

    ok = bool(payload.get("ok"))
    message = str(payload.get("message") or payload.get("detail") or "(no message)")
    return ok, message


def _merge_local_rules() -> tuple[bool, str]:
    repo = os.environ.get("CLAWLAB_REPO", "").strip()
    rules_dir = os.environ.get("DEFENSECLAW_RULES_DIR", "").strip()
    if not repo or not rules_dir:
        return False, "CLAWLAB_REPO / DEFENSECLAW_RULES_DIR not configured."

    script = Path(repo).expanduser() / "admin-access" / "merge-ios-xe-policy.py"
    if not script.is_file():
        return False, f"merge script not found: {script}"

    policy = Path(ios_xe_policy.policy_path())
    try:
        proc = subprocess.run(
            [
                sys.executable,
                str(script),
                "--rules-dir",
                rules_dir,
                "--policy",
                str(policy),
            ],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
            cwd=str(Path(repo).expanduser()),
        )
    except subprocess.TimeoutExpired:
        return False, "merge-ios-xe-policy.py timed out."
    output = ((proc.stdout or "") + (proc.stderr or "")).strip() or "(no output)"
    return proc.returncode == 0, output


def _restart_defenseclaw_gateway() -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["defenseclaw-gateway", "restart"],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
    except FileNotFoundError:
        return False, "defenseclaw-gateway CLI not found on PATH."
    output = ((proc.stdout or "") + (proc.stderr or "")).strip() or "(no output)"
    return proc.returncode == 0, f"defenseclaw-gateway restart:\n{output}"


def reload_enforcement(*, reload_openclaw: bool = False) -> tuple[bool, str]:
    """Merge IOS-XE policy into DefenseClaw and restart enforcement sidecars."""
    messages: list[str] = []

    api_ok, api_msg = _call_defenseclaw_api(reload_openclaw=reload_openclaw)
    messages.append(f"DefenseClaw API: {api_msg}")
    if api_ok:
        return True, "\n\n".join(messages)

    merge_ok, merge_msg = _merge_local_rules()
    messages.append(f"Local merge: {merge_msg}")
    if not merge_ok:
        raise PolicyReloadError(
            "Could not reload policy enforcement.\n\n"
            + "\n\n".join(messages)
            + "\n\nRun on the host: bash admin-access/refresh-clawlab-policies.sh"
        )

    sidecar_ok, sidecar_msg = _restart_defenseclaw_gateway()
    messages.append(sidecar_msg)
    if reload_openclaw:
        try:
            proc = subprocess.run(
                ["systemctl", "--user", "restart", "openclaw-gateway"],
                capture_output=True,
                text=True,
                timeout=45,
                check=False,
            )
        except FileNotFoundError:
            messages.append("openclaw-gateway restart: systemctl not available.")
        else:
            out = ((proc.stdout or "") + (proc.stderr or "")).strip() or "(no output)"
            label = "openclaw-gateway restart"
            if proc.returncode == 0:
                messages.append(f"{label}:\n{out}")
            else:
                messages.append(f"{label} failed:\n{out}")

    ok = merge_ok and sidecar_ok
    return ok, "\n\n".join(messages)
