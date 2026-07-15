"""Persist proposed network changes for human approval before apply."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

CHANGES_DIR = Path(
    os.environ.get("SSH_OPS_CHANGES_DIR", "/data/changes" if Path("/data").is_dir() else "./changes")
).expanduser()

VALID_STATUSES = frozenset({
    "proposed",
    "approved",
    "rejected",
    "applying",
    "applied",
    "failed",
    "rolled_back",
    "expired",
})

_ID_SAFE = re.compile(r"^chg-[0-9]{8}-[0-9]{4,}$")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _path(change_id: str) -> Path:
    if not _ID_SAFE.match(change_id):
        raise ValueError(f"Invalid change id: {change_id}")
    return CHANGES_DIR / f"{change_id}.yaml"


def ensure_dir() -> Path:
    CHANGES_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(CHANGES_DIR, 0o700)
    except OSError:
        pass
    return CHANGES_DIR


def next_id() -> str:
    ensure_dir()
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"chg-{day}-"
    seq = 0
    for path in CHANGES_DIR.glob(f"{prefix}*.yaml"):
        try:
            seq = max(seq, int(path.stem.rsplit("-", 1)[-1]))
        except ValueError:
            continue
    return f"{prefix}{seq + 1:04d}"


def save(change: dict[str, Any]) -> dict[str, Any]:
    ensure_dir()
    cid = change.get("id") or next_id()
    change["id"] = cid
    path = _path(cid)
    path.write_text(yaml.safe_dump(change, sort_keys=False, default_flow_style=False))
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return change


def load(change_id: str) -> dict[str, Any]:
    path = _path(change_id)
    if not path.is_file():
        raise FileNotFoundError(f"Change not found: {change_id}")
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Corrupt change file: {change_id}")
    return data


def list_changes(status: str | None = None) -> list[dict[str, Any]]:
    ensure_dir()
    out: list[dict[str, Any]] = []
    for path in sorted(CHANGES_DIR.glob("chg-*.yaml"), reverse=True):
        try:
            data = yaml.safe_load(path.read_text()) or {}
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        if status and data.get("status") != status:
            continue
        out.append(data)
    return out


def update(change_id: str, **fields: Any) -> dict[str, Any]:
    change = load(change_id)
    change.update(fields)
    change["updated_at"] = _now()
    return save(change)


def set_status(change_id: str, status: str, **extra: Any) -> dict[str, Any]:
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}")
    return update(change_id, status=status, **extra)


def approve(change_id: str, user: str, note: str = "") -> dict[str, Any]:
    change = load(change_id)
    if change.get("status") != "proposed":
        raise ValueError(f"Change {change_id} is not proposed (status={change.get('status')})")
    approvals = list(change.get("approvals") or [])
    approvals.append({
        "user": user,
        "decision": "approved",
        "note": note,
        "ts": _now(),
    })
    return set_status(change_id, "approved", approvals=approvals, approved_at=_now(), approved_by=user)


def reject(change_id: str, user: str, note: str = "") -> dict[str, Any]:
    change = load(change_id)
    if change.get("status") != "proposed":
        raise ValueError(f"Change {change_id} is not proposed (status={change.get('status')})")
    approvals = list(change.get("approvals") or [])
    approvals.append({
        "user": user,
        "decision": "rejected",
        "note": note,
        "ts": _now(),
    })
    return set_status(change_id, "rejected", approvals=approvals, rejected_at=_now(), rejected_by=user)
