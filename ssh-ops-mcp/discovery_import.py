"""
Transform network discovery results into ssh-ops hosts.yaml entries.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

# Device types we do not import into SSH inventory (no CLI ops value).
SKIP_IOS_TYPES = frozenset({"access-point", "ise-appliance"})

# Map discovery ios_type -> ssh-ops platform (netmiko alias).
IOS_TYPE_TO_PLATFORM = {
    "ios-xe": "cisco_ios",
    "ios": "cisco_ios",
    "unknown": "cisco_ios",
}


def staging_path(hosts_yaml: Path) -> Path:
    return hosts_yaml.parent / ".discovery_staging.yaml"


def job_path(hosts_yaml: Path) -> Path:
    return hosts_yaml.parent / ".discovery_job.json"


def load_job(hosts_yaml: Path) -> dict[str, Any]:
    path = job_path(hosts_yaml)
    if not path.is_file():
        return {"status": "idle", "message": ""}
    try:
        import json

        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {"status": "idle", "message": ""}
    except (OSError, ValueError):
        return {"status": "idle", "message": ""}


def save_job(hosts_yaml: Path, job: dict[str, Any]) -> None:
    import json

    path = job_path(hosts_yaml)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(job, fh)


def clear_job(hosts_yaml: Path) -> None:
    path = job_path(hosts_yaml)
    if path.is_file():
        path.unlink()


def sanitize_host_key(hostname: str, ip: str) -> str:
    """Produce a stable, unique hosts.yaml key from hostname or IP."""
    base = (hostname or "").split(".")[0].strip().lower()
    base = re.sub(r"[^a-z0-9_-]+", "-", base).strip("-")
    if not base or base == "unknown":
        base = ip.replace(".", "-")
    return base[:48] or ip.replace(".", "-")


def build_tags(device: dict[str, Any]) -> list[str]:
    tags: list[str] = ["discovered", "network"]
    ios_type = str(device.get("ios_type") or "").strip().lower()
    if ios_type and ios_type != "unknown":
        tags.append(ios_type)
    model = str(device.get("model") or "").strip()
    if model and model.lower() != "unknown":
        # Short model token for filtering (e.g. C9300-24T -> c9300-24t).
        tags.append(re.sub(r"[^a-zA-Z0-9_-]+", "", model).lower()[:32])
    mgmt = str(device.get("management_type") or "").strip().lower()
    if mgmt and mgmt != "unknown":
        tags.append(mgmt.replace(" ", "-"))
    return tags


def is_importable(device: dict[str, Any]) -> bool:
    ios_type = str(device.get("ios_type") or "unknown").strip().lower()
    if ios_type in SKIP_IOS_TYPES:
        return False
    ip = str(device.get("ip") or "").strip()
    return bool(ip)


def device_to_host_entry(device: dict[str, Any], username: str) -> dict[str, Any]:
    """Build a hosts.yaml host dict (passwords stored separately via secrets_store)."""
    platform = IOS_TYPE_TO_PLATFORM.get(
        str(device.get("ios_type") or "unknown").strip().lower(),
        "cisco_ios",
    )
    tags = device.get("tags")
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    elif not tags:
        tags = build_tags(device)
    entry: dict[str, Any] = {
        "hostname": str(device["ip"]).strip(),
        "platform": platform,
        "port": 22,
        "username": username,
        "tags": tags,
        "allow_write": False,
    }
    return entry


def normalize_staged_device(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a staged device record from form/API input."""
    device: dict[str, Any] = {
        "ip": str(raw.get("ip") or "").strip(),
        "hostname": str(raw.get("hostname") or "").strip(),
        "model": str(raw.get("model") or "").strip(),
        "ios_type": str(raw.get("ios_type") or "unknown").strip().lower(),
        "management_type": str(raw.get("management_type") or "").strip(),
    }
    if raw.get("version"):
        device["version"] = str(raw.get("version")).strip()
    if raw.get("serial"):
        device["serial"] = str(raw.get("serial")).strip()
    host_key = str(raw.get("host_key") or "").strip()
    if host_key:
        device["host_key"] = host_key
    tags = raw.get("tags")
    if isinstance(tags, str) and tags.strip():
        device["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
    elif isinstance(tags, list):
        device["tags"] = [str(t).strip() for t in tags if str(t).strip()]
    return device


def host_key_for_device(device: dict[str, Any], hosts: dict[str, Any]) -> str:
    """Resolve inventory key for a staged device."""
    ip = str(device.get("ip") or "").strip()
    hostname = str(device.get("hostname") or ip).strip()
    override = str(device.get("host_key") or "").strip()
    if override:
        key = sanitize_host_key(override, ip)
    else:
        key = sanitize_host_key(hostname, ip)
    if key in hosts:
        suffix = ip.replace(".", "")
        key = f"{key}-{suffix}"[:56]
    return key


def load_staging(hosts_yaml: Path) -> list[dict[str, Any]]:
    path = staging_path(hosts_yaml)
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    devices = data.get("discovered_devices") or []
    return [d for d in devices if isinstance(d, dict)]


def save_staging(hosts_yaml: Path, devices: list[dict[str, Any]], meta: dict[str, Any] | None = None) -> Path:
    path = staging_path(hosts_yaml)
    payload: dict[str, Any] = {"discovered_devices": devices}
    if meta:
        payload["meta"] = meta
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(payload, fh, default_flow_style=False, sort_keys=False)
    return path


def clear_staging(hosts_yaml: Path) -> None:
    path = staging_path(hosts_yaml)
    if path.is_file():
        path.unlink()


def parse_upload_yaml(content: str) -> list[dict[str, Any]]:
    data = yaml.safe_load(content) or {}
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    devices = data.get("discovered_devices") or data.get("devices") or []
    return [d for d in devices if isinstance(d, dict)]


def merge_selected_into_hosts(
    cfg: dict[str, Any],
    devices: list[dict[str, Any]],
    selected_indices: list[int],
    *,
    username: str,
    login_password: str,
    enable_password: str | None,
    secrets_store: Any,
) -> tuple[int, int, list[str]]:
    """
    Add selected devices to cfg['hosts']. Returns (added, skipped, messages).

    secrets_store: module with set_host_secret(host_key, field, value).
    """
    hosts: dict[str, Any] = cfg.setdefault("hosts", {})
    added = 0
    skipped = 0
    messages: list[str] = []

    for idx in selected_indices:
        if idx < 0 or idx >= len(devices):
            continue
        device = devices[idx]
        if not is_importable(device):
            skipped += 1
            messages.append(f"Skipped {device.get('hostname', '?')} ({device.get('ip')}): not importable")
            continue

        ip = str(device["ip"]).strip()
        hostname = str(device.get("hostname") or ip).strip()
        key = host_key_for_device(device, hosts)
        if key in hosts:
            skipped += 1
            messages.append(f"Skipped {hostname}: already in inventory as {key}")
            continue

        entry = device_to_host_entry(device, username)
        hosts[key] = entry
        secrets_store.set_secret(key, "login", login_password)
        if enable_password:
            secrets_store.set_secret(key, "enable", enable_password)
        added += 1
        messages.append(f"Added {key} ({ip}, {hostname})")

    return added, skipped, messages
