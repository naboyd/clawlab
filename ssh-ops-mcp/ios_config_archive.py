"""Archive IOS running-config snapshots, detect out-of-band drift, notify Webex."""

from __future__ import annotations

import difflib
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

import change_store
import inventory
import network_apply

log = logging.getLogger("ssh_ops.ios_archive")

ARCHIVE_DIR = Path(
    os.environ.get(
        "SSH_OPS_IOS_ARCHIVE_DIR",
        "/data/ios-config-archive" if Path("/data").is_dir() else "./ios-config-archive",
    )
).expanduser()

# Lines that change every save but are not meaningful config drift.
_VOLATILE_PATTERNS = [
    re.compile(r"^! Last configuration change at .*", re.I),
    re.compile(r"^! NVRAM config last updated at .*", re.I),
    re.compile(r"^!Time: .*", re.I),
    re.compile(r"^Using \d+ out of .*", re.I),
    re.compile(r"^Current configuration : \d+ bytes", re.I),
    re.compile(r"^! \d+ bytes.*", re.I),
    re.compile(r"^Building configuration\.\.\.", re.I),
    re.compile(r"^Cryptochecksum:.*", re.I),
    re.compile(r"^!\s*$"),
]

_get_host: Callable[[str], dict[str, Any]] | None = None
_platform_fn: Callable[[dict[str, Any]], str] | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def configure_runtime(
    *,
    get_host: Callable[[str], dict[str, Any]],
    platform_fn: Callable[[dict[str, Any]], str],
    netmiko_type_fn: Callable[[str], str],
    expand_fn: Callable[[str | None], str | None],
    connect_timeout: int = 10,
    command_timeout: int = 120,
) -> None:
    global _get_host, _platform_fn
    _get_host = get_host
    _platform_fn = platform_fn
    network_apply.configure(
        get_host=get_host,
        platform_fn=platform_fn,
        netmiko_type_fn=netmiko_type_fn,
        expand_fn=expand_fn,
        connect_timeout=connect_timeout,
        command_timeout=command_timeout,
    )


def _expand(p: str | None) -> str | None:
    return str(Path(os.path.expanduser(p)).resolve()) if p else None


def configure_from_env() -> None:
    """Bootstrap network_apply from SSH_OPS_CONFIG (CLI / systemd, no MCP server)."""
    config_path = os.environ.get("SSH_OPS_CONFIG", "hosts.yaml")
    cfg_file = Path(os.path.expanduser(config_path))
    if not cfg_file.is_file():
        raise FileNotFoundError(f"Config not found: {cfg_file}")
    cfg = yaml.safe_load(cfg_file.read_text()) or {}
    settings = cfg.get("settings") or {}
    hosts: dict[str, dict[str, Any]] = cfg.get("hosts") or {}
    if not hosts:
        raise ValueError("No hosts in config")

    netmiko_aliases = {
        "ios": "cisco_ios",
        "ios-xe": "cisco_ios",
        "iosxe": "cisco_ios",
        "cisco": "cisco_ios",
        "cisco_ios": "cisco_ios",
        "cisco_xe": "cisco_xe",
        "nxos": "cisco_nxos",
        "cisco_nxos": "cisco_nxos",
    }

    def platform_fn(h: dict[str, Any]) -> str:
        return str(h.get("platform", "linux") or "linux").strip().lower()

    def get_host(name: str) -> dict[str, Any]:
        if name not in hosts:
            raise ValueError(f"Unknown host '{name}'")
        return hosts[name]

    configure_runtime(
        get_host=get_host,
        platform_fn=platform_fn,
        netmiko_type_fn=lambda p: netmiko_aliases.get(p, p),
        expand_fn=_expand,
        connect_timeout=int(settings.get("connect_timeout", 10)),
        command_timeout=int(settings.get("command_timeout", 120)),
    )


def is_network_host(h: dict[str, Any]) -> bool:
    plat = str(h.get("platform", "linux") or "linux").strip().lower()
    return plat not in ("linux", "unix", "")


def archive_enabled(h: dict[str, Any]) -> bool:
    if inventory.has_tag(h, "no_config_archive"):
        return False
    if inventory.has_tag(h, "config_archive"):
        return True
    return is_network_host(h)


def normalize_config(text: str) -> str:
    """Drop volatile IOS lines so timestamps do not look like drift."""
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").splitlines():
        line = raw.rstrip()
        if any(p.match(line) for p in _VOLATILE_PATTERNS):
            continue
        lines.append(line)
    return "\n".join(lines).strip() + "\n"


def host_dir(host_name: str) -> Path:
    return ARCHIVE_DIR / host_name


def baseline_path(host_name: str) -> Path:
    return host_dir(host_name) / "baseline.txt"


def meta_path(host_name: str) -> Path:
    return host_dir(host_name) / "meta.json"


def _read_meta(host_name: str) -> dict[str, Any]:
    path = meta_path(host_name)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_meta(host_name: str, meta: dict[str, Any]) -> None:
    path = meta_path(host_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, indent=2) + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def unified_diff(baseline: str, current: str, *, host_name: str) -> str:
    base_lines = normalize_config(baseline).splitlines(keepends=True)
    cur_lines = normalize_config(current).splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(
            base_lines,
            cur_lines,
            fromfile=f"{host_name}/baseline",
            tofile=f"{host_name}/current",
        )
    )


def has_meaningful_diff(diff_text: str) -> bool:
    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            return True
        if line.startswith("-") and not line.startswith("---"):
            return True
    return False


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def _change_targets_host(change: dict[str, Any], host_name: str) -> bool:
    for target in change.get("targets") or []:
        if isinstance(target, dict) and str(target.get("name") or "") == host_name:
            return True
    return False


def _ios_change_types() -> frozenset[str]:
    return frozenset({
        "ios_config_lines",
        "ios_local_user",
        "ios_interface_state",
    })


def find_in_band_changes(
    host_name: str,
    *,
    since_iso: str | None,
) -> list[dict[str, Any]]:
    """Applied (or recently applied) gated changes on this host since baseline."""
    since = _parse_iso(since_iso)
    matches: list[dict[str, Any]] = []
    for change in change_store.list_changes():
        status = change.get("status")
        if status not in ("applied", "applying"):
            continue
        if change.get("change_type") not in _ios_change_types():
            continue
        if not _change_targets_host(change, host_name):
            continue
        finished = _parse_iso(change.get("apply_finished_at") or change.get("updated_at"))
        if since and finished and finished < since:
            continue
        matches.append(change)
    return matches


def archive_snapshot(host_name: str, config_text: str, *, label: str) -> Path:
    snap_dir = host_dir(host_name) / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    path = snap_dir / f"{label}.txt"
    path.write_text(config_text)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def save_drift_artifacts(
    host_name: str,
    *,
    diff_text: str,
    new_config: str,
    stamp: str,
) -> dict[str, str]:
    diff_dir = host_dir(host_name) / "diffs"
    diff_dir.mkdir(parents=True, exist_ok=True)
    diff_path = diff_dir / f"{stamp}.diff"
    new_path = diff_dir / f"{stamp}-new.txt"
    diff_path.write_text(diff_text)
    new_path.write_text(new_config)
    for p in (diff_path, new_path):
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
    return {"diff": str(diff_path), "new_config": str(new_path)}


def set_baseline(host_name: str, config_text: str, *, reason: str) -> Path:
    path = baseline_path(host_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(config_text)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    meta = _read_meta(host_name)
    meta.update({
        "baseline_updated_at": _now_iso(),
        "baseline_reason": reason,
        "baseline_path": str(path),
    })
    _write_meta(host_name, meta)
    return path


def fetch_running_config(host_name: str) -> str:
    if _get_host is None:
        raise RuntimeError("ios_config_archive.configure_runtime() was not called")
    tmp = host_dir(host_name) / ".fetch-tmp"
    path = network_apply.backup_running_config(host_name, tmp)
    return path.read_text()


def check_host_drift(host_name: str, *, notify: bool = True) -> dict[str, Any]:
    """Compare live config to baseline; alert on unexplained drift."""
    result: dict[str, Any] = {"host": host_name, "drift": False}
    try:
        current = fetch_running_config(host_name)
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    stamp = _now_stamp()
    archive_snapshot(host_name, current, label=stamp)
    result["snapshot"] = str(host_dir(host_name) / "snapshots" / f"{stamp}.txt")

    base_file = baseline_path(host_name)
    if not base_file.is_file():
        set_baseline(host_name, current, reason="initial_baseline")
        result["status"] = "baseline_initialized"
        return result

    baseline = base_file.read_text()
    diff_text = unified_diff(baseline, current, host_name=host_name)
    if not has_meaningful_diff(diff_text):
        result["status"] = "unchanged"
        return result

    meta = _read_meta(host_name)
    in_band = find_in_band_changes(host_name, since_iso=meta.get("baseline_updated_at"))
    result["diff_lines"] = len(diff_text.splitlines())

    if in_band:
        change_ids = [c.get("id") for c in in_band if c.get("id")]
        set_baseline(host_name, current, reason=f"in_band:{','.join(change_ids)}")
        result["status"] = "changed_in_band"
        result["drift"] = False
        result["matched_changes"] = change_ids
        return result

    artifacts = save_drift_artifacts(
        host_name,
        diff_text=diff_text,
        new_config=current,
        stamp=stamp,
    )
    set_baseline(host_name, current, reason="oob_drift_accepted")
    result["status"] = "out_of_band"
    result["drift"] = True
    result["artifacts"] = artifacts
    result["diff_preview"] = "\n".join(diff_text.splitlines()[:40])

    if notify:
        try:
            import change_notify

            result["notify"] = change_notify.notify_ios_config_oob_drift(
                host_name,
                diff_text=diff_text,
                artifacts=artifacts,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("oob notify failed host=%s err=%s", host_name, exc)
            result["notify_error"] = str(exc)

    return result


def list_archive_hosts(hosts: dict[str, dict[str, Any]]) -> list[str]:
    return sorted(
        name
        for name, h in hosts.items()
        if archive_enabled(h)
    )


def run_daily_check(
    hosts: dict[str, dict[str, Any]] | None = None,
    *,
    notify: bool = True,
) -> dict[str, Any]:
    """Archive and diff all in-scope network hosts."""
    if hosts is None:
        if _get_host is None:
            raise RuntimeError("configure_runtime() or configure_from_env() required")
        config_path = os.environ.get("SSH_OPS_CONFIG", "hosts.yaml")
        cfg = yaml.safe_load(Path(os.path.expanduser(config_path)).read_text()) or {}
        hosts = cfg.get("hosts") or {}

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(ARCHIVE_DIR, 0o700)
    except OSError:
        pass

    names = list_archive_hosts(hosts)
    results: list[dict[str, Any]] = []
    oob_hosts: list[str] = []

    for name in names:
        log.info("ios archive check host=%s", name)
        row = check_host_drift(name, notify=notify)
        results.append(row)
        if row.get("drift"):
            oob_hosts.append(name)

    summary = {
        "checked_at": _now_iso(),
        "archive_dir": str(ARCHIVE_DIR),
        "hosts_checked": len(names),
        "out_of_band": oob_hosts,
        "results": results,
    }
    report_path = ARCHIVE_DIR / "last-run.json"
    report_path.write_text(json.dumps(summary, indent=2) + "\n")
    return summary
