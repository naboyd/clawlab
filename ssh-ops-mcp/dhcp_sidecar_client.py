"""HTTP client for host-local isc-dhcp sidecars (127.0.0.1:9080 via SSH curl)."""

from __future__ import annotations

import json
import shlex
from typing import Any, Callable

import inventory
import secrets_store

_get_host: Callable[[str], dict[str, Any]] | None = None
_ssh_run: Callable[..., dict[str, Any]] | None = None
_sidecar_port = 9080


def configure(
    *,
    get_host: Callable[[str], dict[str, Any]],
    ssh_run: Callable[..., dict[str, Any]],
    sidecar_port: int = 9080,
) -> None:
    global _get_host, _ssh_run, _sidecar_port
    _get_host = get_host
    _ssh_run = ssh_run
    _sidecar_port = sidecar_port


def _require_configured() -> tuple[Callable[[str], dict[str, Any]], Callable[..., dict[str, Any]]]:
    if _get_host is None or _ssh_run is None:
        raise RuntimeError("dhcp_sidecar_client.configure() was not called")
    return _get_host, _ssh_run


def is_dhcp_host(host: dict[str, Any]) -> bool:
    sidecar = host.get("dhcp_sidecar")
    if isinstance(sidecar, dict) and sidecar:
        return True
    if inventory.has_tag(host, "dhcp"):
        return True
    services = host.get("allowed_services") or []
    return any(str(s).strip() == "isc-dhcp-server" for s in services)


def sidecar_port(host: dict[str, Any]) -> int:
    sidecar = host.get("dhcp_sidecar")
    if isinstance(sidecar, dict):
        try:
            return int(sidecar.get("port") or _sidecar_port)
        except (TypeError, ValueError):
            pass
    return _sidecar_port


def get_sidecar_token(host_name: str) -> str:
    try:
        token = secrets_store.get_secret(host_name, "sidecar")
    except secrets_store.DecryptionError as exc:
        raise RuntimeError(str(exc)) from exc
    if not token:
        raise RuntimeError(
            f"No dhcp sidecar token for '{host_name}'. "
            f"Store with: python secrets_store.py set sidecar {host_name} TOKEN"
        )
    return token


def _parse_json_response(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("error"):
        raise RuntimeError(str(result["error"]))
    exit_raw = result.get("exit_code")
    exit_code = 1 if exit_raw is None else int(exit_raw)
    stdout = (result.get("stdout") or "").strip()
    stderr = (result.get("stderr") or "").strip()
    if exit_code != 0:
        detail = stderr or stdout or f"curl exit {exit_code}"
        raise RuntimeError(detail)
    if not stdout:
        raise RuntimeError("empty response from sidecar")
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid JSON from sidecar: {stdout[:200]}") from exc


def _api(
    host_name: str,
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    get_host, ssh_run = _require_configured()
    host = get_host(host_name)
    if not is_dhcp_host(host):
        raise RuntimeError(f"Host '{host_name}' is not configured for dhcp sidecar")
    token = get_sidecar_token(host_name)
    port = sidecar_port(host)
    url = f"http://127.0.0.1:{port}{path}"
    cmd_parts = [
        "curl",
        "-sfS",
        "-X",
        method,
        "-H",
        f"Authorization: Bearer {token}",
        url,
    ]
    if body is not None:
        payload = json.dumps(body, separators=(",", ":"))
        cmd_parts.extend(["-H", "Content-Type: application/json", "-d", payload])
    command = " ".join(shlex.quote(part) for part in cmd_parts)
    return _parse_json_response(ssh_run(host_name, command))


def run_ssh(host_name: str, command: str) -> dict[str, Any]:
    _require_configured()
    assert _ssh_run is not None
    return _ssh_run(host_name, command)


def health(host_name: str) -> dict[str, Any]:
    get_host, ssh_run = _require_configured()
    host = get_host(host_name)
    port = sidecar_port(host)
    command = f"curl -sfS http://127.0.0.1:{port}/health"
    return _parse_json_response(ssh_run(host_name, command))


def list_includes(host_name: str) -> dict[str, Any]:
    return _api(host_name, "GET", "/api/includes")


def get_include(host_name: str, name: str) -> dict[str, Any]:
    return _api(host_name, "GET", f"/api/includes/{name}")


def validate_include(host_name: str, name: str, content: str) -> dict[str, Any]:
    return _api(
        host_name,
        "POST",
        f"/api/includes/{name}/validate",
        body={"content": content},
    )


def apply_include(
    host_name: str,
    name: str,
    content: str,
    *,
    change_id: str,
    actor: str = "mcp",
) -> dict[str, Any]:
    return _api(
        host_name,
        "POST",
        f"/api/includes/{name}/apply",
        body={"change_id": change_id, "content": content, "actor": actor},
    )


def rollback(host_name: str, change_id: str, *, actor: str = "mcp") -> dict[str, Any]:
    return _api(
        host_name,
        "POST",
        f"/api/rollback/{change_id}",
        body={"actor": actor},
    )
