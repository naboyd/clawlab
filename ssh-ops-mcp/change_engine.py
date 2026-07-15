"""Build, apply, and roll back approval-gated network changes."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import change_policy
import change_store
import change_notify
import ios_change
import network_apply

_BACKUPS_DIR = Path(
    os.environ.get(
        "SSH_OPS_CHANGE_BACKUPS_DIR",
        "/data/change-backups" if Path("/data").is_dir() else "./change-backups",
    )
).expanduser()


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _redact_change(change: dict[str, Any]) -> dict[str, Any]:
    out = dict(change)
    if isinstance(out.get("spec"), dict):
        out["spec"] = ios_change.public_spec(out["spec"])
    targets = []
    for t in out.get("targets") or []:
        if not isinstance(t, dict):
            continue
        tt = dict(t)
        if "apply" in tt:
            redacted = []
            for line in tt.get("apply") or []:
                if " secret " in str(line):
                    head, _ = str(line).split(" secret ", 1)
                    redacted.append(f"{head} secret ***")
                else:
                    redacted.append(str(line))
            tt["apply"] = redacted
        targets.append(tt)
    out["targets"] = targets
    return out


def propose_change(
    *,
    host: str,
    change_type: str,
    spec: dict[str, Any],
    intent: str = "",
    created_by: str = "agent",
    get_host,
    platform_fn,
) -> dict[str, Any]:
    try:
        h = get_host(host)
    except ValueError as exc:
        return {"error": str(exc)}

    platform = platform_fn(h)
    risk, errors, warnings = change_policy.validate_proposal(
        change_type, spec, platform=platform
    )
    if errors:
        return {"error": "Proposal rejected", "risk": risk, "errors": errors, "warnings": warnings}

    if change_type == "ios_local_user":
        target = ios_change.build_ios_local_user_target(host, platform, spec)
    elif change_type == "ios_interface_state":
        target = ios_change.build_ios_interface_state_target(host, platform, spec)
    elif change_type == "ios_config_lines":
        target = ios_change.build_ios_config_lines_target(host, platform, spec)
    else:
        return {"error": f"Unsupported change_type: {change_type}"}

    cid = change_store.next_id()
    change = {
        "id": cid,
        "intent": intent or target.get("summary", ""),
        "change_type": change_type,
        "spec": spec,
        "risk": risk,
        "status": "proposed",
        "created_by": created_by,
        "created_at": _now(),
        "updated_at": _now(),
        "approvals": [],
        "warnings": warnings,
        "policy_group": target.get("policy_group") or spec.get("_policy_group"),
        "targets": [target],
    }
    change_store.save(change)
    return {
        "change_id": cid,
        "status": "proposed",
        "risk": risk,
        "warnings": warnings,
        "intent": change["intent"],
        "targets": [
            {
                "name": target["name"],
                "summary": target.get("summary"),
                "apply_preview": target.get("apply"),
                "rollback_preview": target.get("rollback"),
                "verify": target.get("verify"),
            }
        ],
        "message": "Change proposed. A human must approve it in MCP Admin before apply_change.",
    }


def get_change(change_id: str, *, redact: bool = True) -> dict[str, Any]:
    try:
        change = change_store.load(change_id)
    except FileNotFoundError:
        return {"error": f"Change not found: {change_id}"}
    return _redact_change(change) if redact else change


def list_changes(status: str | None = None, *, redact: bool = True) -> list[dict[str, Any]]:
    items = change_store.list_changes(status=status)
    return [_redact_change(c) if redact else c for c in items]


def apply_change(change_id: str, *, actor: str = "mcp") -> dict[str, Any]:
    try:
        change = change_store.load(change_id)
    except FileNotFoundError:
        return {"error": f"Change not found: {change_id}"}

    if change.get("status") != "approved":
        return {
            "error": f"Change {change_id} is not approved (status={change.get('status')}). "
            "Approve it in MCP Admin first.",
        }

    change_store.set_status(change_id, "applying", apply_started_at=_now(), apply_actor=actor)
    results: list[dict[str, Any]] = []
    all_ok = True

    for target in change.get("targets") or []:
        host = target["name"]
        apply_lines = list(target.get("apply") or [])
        tr: dict[str, Any] = {"host": host, "steps": []}
        try:
            backup_dir = _BACKUPS_DIR / change_id
            backup_path = network_apply.backup_running_config(host, backup_dir)
            tr["steps"].append({"step": "backup", "path": str(backup_path)})

            if apply_lines:
                out = network_apply.apply_config_lines(host, apply_lines)
                tr["steps"].append({"step": "apply", "output": out})

            verified, verify_results = network_apply.verify_target(target)
            tr["steps"].append({"step": "verify", "passed": verified, "results": verify_results})
            if not verified:
                all_ok = False
                tr["error"] = "Verification failed"
                rollback_lines = list(target.get("rollback") or [])
                if rollback_lines:
                    network_apply.apply_config_lines(host, rollback_lines)
                    tr["steps"].append({"step": "auto_rollback", "lines": len(rollback_lines)})
                results.append(tr)
                continue

            save_out = network_apply.write_memory(host)
            tr["steps"].append({"step": "write_memory", "output": save_out})
            tr["ok"] = True
        except Exception as exc:  # noqa: BLE001
            all_ok = False
            tr["error"] = f"{type(exc).__name__}: {exc}"
            rollback_lines = list(target.get("rollback") or [])
            if rollback_lines:
                try:
                    network_apply.apply_config_lines(host, rollback_lines)
                    tr["steps"].append({"step": "auto_rollback", "lines": len(rollback_lines)})
                except Exception as rb_exc:  # noqa: BLE001
                    tr["rollback_error"] = f"{type(rb_exc).__name__}: {rb_exc}"
        results.append(tr)

    if all_ok:
        applied = change_store.set_status(
            change_id,
            "applied",
            apply_finished_at=_now(),
            apply_results=results,
        )
        try:
            notify_result = change_notify.notify_change_applied(applied, actor=actor)
        except Exception as exc:  # noqa: BLE001
            notify_result = {"error": str(exc)}
        return {
            "change_id": change_id,
            "status": "applied",
            "results": results,
            "notify": notify_result,
        }

    change_store.set_status(
        change_id,
        "failed",
        apply_finished_at=_now(),
        apply_results=results,
    )
    return {"change_id": change_id, "status": "failed", "results": results, "error": "One or more targets failed"}


def rollback_change(change_id: str, *, actor: str = "mcp") -> dict[str, Any]:
    try:
        change = change_store.load(change_id)
    except FileNotFoundError:
        return {"error": f"Change not found: {change_id}"}

    if change.get("status") not in ("applied", "failed"):
        return {
            "error": f"Change {change_id} cannot be rolled back from status={change.get('status')}",
        }

    results: list[dict[str, Any]] = []
    all_ok = True
    for target in change.get("targets") or []:
        host = target["name"]
        rollback_lines = list(target.get("rollback") or [])
        tr: dict[str, Any] = {"host": host, "steps": []}
        if not rollback_lines:
            tr["ok"] = True
            tr["note"] = "No rollback lines stored"
            results.append(tr)
            continue
        try:
            network_apply.backup_running_config(host, _BACKUPS_DIR / f"{change_id}-rollback")
            out = network_apply.apply_config_lines(host, rollback_lines)
            tr["steps"].append({"step": "rollback", "output": out})
            rb_target = dict(target)
            spec = change.get("spec") or {}
            if change.get("change_type") == "ios_interface_state":
                state = ios_change.normalize_interface_state(spec)
                rb_target["verify_expect"] = "admin_up" if state == "shutdown" else "admin_down"
            elif change.get("change_type") == "ios_local_user":
                action = str(spec.get("action") or "create").lower()
                rb_target["verify_expect"] = "config_absent" if action == "create" else "config_present"
            elif change.get("change_type") == "ios_config_lines":
                rb_target["verify_expect"] = "config_absent"
            verified, verify_results = network_apply.verify_target(rb_target)
            tr["steps"].append({"step": "verify", "passed": verified, "results": verify_results})
            if not verified:
                all_ok = False
                tr["error"] = "Post-rollback verification failed"
            else:
                save_out = network_apply.write_memory(host)
                tr["steps"].append({"step": "write_memory", "output": save_out})
                tr["ok"] = True
        except Exception as exc:  # noqa: BLE001
            all_ok = False
            tr["error"] = f"{type(exc).__name__}: {exc}"
        results.append(tr)

    status = "rolled_back" if all_ok else "failed"
    change_store.set_status(
        change_id,
        status,
        rollback_finished_at=_now(),
        rollback_actor=actor,
        rollback_results=results,
    )
    return {"change_id": change_id, "status": status, "results": results}
