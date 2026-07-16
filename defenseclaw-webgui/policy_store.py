#!/usr/bin/env python3
"""DefenseClaw policy file helpers for the web GUI."""

from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import yaml

DEFENSECLAW_HOME = Path(
    os.environ.get("DEFENSECLAW_HOME", Path.home() / ".defenseclaw")
).expanduser()
CONFIG_PATH = Path(
    os.environ.get("DEFENSECLAW_CONFIG", DEFENSECLAW_HOME / "config.yaml")
).expanduser()
ENV_PATH = Path(
    os.environ.get("DEFENSECLAW_ENV", DEFENSECLAW_HOME / ".env")
).expanduser()

BUNDLED_RULE_PACKS = ("permissive", "default", "strict")
ACTION_KINDS = ("skill_actions", "mcp_actions", "plugin_actions")
SEVERITIES = ("critical", "high", "medium", "low", "info")
ACTION_FIELDS = ("file", "runtime", "install")
ACTION_VALUES = ("none", "enable", "disable", "block", "quarantine")

SECRET_KEY_PATTERN = re.compile(
    r"(api_key|secret|token|password|private_key)", re.IGNORECASE
)


class PolicyError(RuntimeError):
    """Raised when a policy operation fails."""


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise PolicyError(f"Config not found: {CONFIG_PATH}")
    return yaml.safe_load(CONFIG_PATH.read_text()) or {}


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(
        yaml.safe_dump(cfg, sort_keys=False, default_flow_style=False)
    )
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass


def resolve_path(value: str | None, base: Path | None = None) -> Path | None:
    if not value:
        return None
    p = Path(os.path.expanduser(value))
    if not p.is_absolute() and base:
        p = (base / p).resolve()
    return p.expanduser()


def policy_dir(cfg: dict | None = None) -> Path:
    cfg = cfg or load_config()
    return resolve_path(cfg.get("policy_dir"), DEFENSECLAW_HOME) or (
        DEFENSECLAW_HOME / "policies"
    )


def rule_pack_dir(cfg: dict | None = None) -> Path:
    cfg = cfg or load_config()
    guardrail = cfg.get("guardrail") or {}
    explicit = resolve_path(guardrail.get("rule_pack_dir"), DEFENSECLAW_HOME)
    if explicit:
        return explicit
    return policy_dir(cfg) / "guardrail" / "strict"


def firewall_path(cfg: dict | None = None) -> Path:
    cfg = cfg or load_config()
    fw = cfg.get("firewall") or {}
    return resolve_path(fw.get("config_file"), DEFENSECLAW_HOME) or (
        DEFENSECLAW_HOME / "firewall.yaml"
    )


def list_named_policies(cfg: dict | None = None) -> list[str]:
    pdir = policy_dir(cfg)
    if not pdir.exists():
        return []
    names: list[str] = []
    for path in sorted(pdir.glob("*.yaml")):
        if path.name.startswith("."):
            continue
        names.append(path.stem)
    return names


def list_rule_pack_files(pack_dir: Path | None = None) -> list[Path]:
    root = pack_dir or rule_pack_dir()
    if not root.exists():
        return []
    files: list[Path] = []
    for path in sorted(root.rglob("*.yaml")):
        if path.is_file():
            files.append(path)
    return files


def read_text_file(path: Path) -> str:
    if not path.exists():
        raise PolicyError(f"File not found: {path}")
    return path.read_text()


def write_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_yaml_file(path: Path) -> dict:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text())
    return data if isinstance(data, dict) else {}


def save_yaml_file(path: Path, data: dict) -> None:
    write_text_file(
        path,
        yaml.safe_dump(data, sort_keys=False, default_flow_style=False),
    )


def env_var_set(name: str | None) -> bool:
    if not name:
        return False
    if os.environ.get(name):
        return True
    if not ENV_PATH.exists():
        return False
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        if key.strip() == name and val.strip():
            return True
    return False


def redact_config(cfg: dict) -> dict:
    """Return a copy safe to display — secrets replaced with placeholders."""

    def walk(node):
        if isinstance(node, dict):
            out = {}
            for key, value in node.items():
                if isinstance(value, str) and SECRET_KEY_PATTERN.search(key):
                    out[key] = "<set>" if value else ""
                elif key.endswith("_env") and isinstance(value, str):
                    out[key] = value
                    status_key = f"{key}__set"
                    out[status_key] = env_var_set(value)
                else:
                    out[key] = walk(value)
            return out
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    return walk(cfg)


def validate_config() -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["defenseclaw", "config", "validate"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except FileNotFoundError:
        return True, "defenseclaw CLI not found — skipped validate."
    except subprocess.TimeoutExpired:
        return False, "defenseclaw config validate timed out."

    output = (proc.stdout or "") + (proc.stderr or "")
    output = output.strip() or "(no output)"
    return proc.returncode == 0, output


def policy_validate() -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["defenseclaw", "policy", "validate"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except FileNotFoundError:
        return True, "defenseclaw CLI not found — skipped policy validate."
    except subprocess.TimeoutExpired:
        return False, "defenseclaw policy validate timed out."

    output = (proc.stdout or "") + (proc.stderr or "")
    output = output.strip() or "(no output)"
    return proc.returncode == 0, output


def activate_policy(name: str) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["defenseclaw", "policy", "activate", name],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except FileNotFoundError:
        return False, "defenseclaw CLI not found."
    except subprocess.TimeoutExpired:
        return False, "defenseclaw policy activate timed out."

    output = (proc.stdout or "") + (proc.stderr or "")
    output = output.strip() or "(no output)"
    return proc.returncode == 0, output


def reload_gateway() -> tuple[bool, str]:
    """Reload DefenseClaw sidecar and OpenClaw gateway (best-effort for each)."""
    outputs: list[str] = []
    ok_any = False
    for cmd in (
        ["defenseclaw-gateway", "restart"],
        ["systemctl", "--user", "restart", "openclaw-gateway"],
    ):
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except FileNotFoundError:
            continue
        output = ((proc.stdout or "") + (proc.stderr or "")).strip() or "(no output)"
        label = " ".join(cmd)
        if proc.returncode == 0:
            ok_any = True
            outputs.append(f"{label}:\n{output}")
        else:
            outputs.append(f"{label} failed:\n{output}")
    if not outputs:
        return False, "No gateway reload command available."
    return ok_any, "\n\n".join(outputs)


def reload_defenseclaw_gateway() -> tuple[bool, str]:
    """Reload only the DefenseClaw sidecar (safe after IOS-XE rule merge)."""
    try:
        proc = subprocess.run(
            ["defenseclaw-gateway", "restart"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except FileNotFoundError:
        return False, "defenseclaw-gateway CLI not found."
    output = ((proc.stdout or "") + (proc.stderr or "")).strip() or "(no output)"
    return proc.returncode == 0, f"defenseclaw-gateway restart:\n{output}"


def recent_audit_events(limit: int = 50) -> list[dict]:
    db_path = DEFENSECLAW_HOME / "audit.db"
    if not db_path.exists():
        return []

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "audit_events" not in tables:
            return []
        rows = conn.execute(
            """
            SELECT rowid, ts, action, severity, target, detail, connector
            FROM audit_events
            ORDER BY rowid DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()

    return [dict(row) for row in rows]


def relative_to_home(path: Path) -> str:
    try:
        return str(path.relative_to(DEFENSECLAW_HOME))
    except ValueError:
        return str(path)


def clawlab_repo() -> Path:
    """Clawlab checkout used for ios-xe-policy templates and merge scripts."""
    env = os.environ.get("CLAWLAB_REPO", "").strip()
    if env:
        candidate = Path(env).expanduser()
        if candidate.is_dir():
            return candidate
    bundled = Path(__file__).resolve().parent.parent
    if (bundled / "config-templates" / "ios-xe-policy.yaml").is_file():
        return bundled
    return Path.home() / "clawlab"


def ios_xe_policy_path() -> Path:
    """Canonical ios-xe-policy.yaml for the DefenseClaw admin editor."""
    for key in ("IOS_XE_POLICY_PATH", "SSH_OPS_IOS_XE_POLICY"):
        env = os.environ.get(key, "").strip()
        if env:
            return Path(env).expanduser()
    return clawlab_repo() / "config-templates" / "ios-xe-policy.yaml"


def ios_xe_policy_mirror_paths() -> list[Path]:
    """Additional locations updated when saving from the DefenseClaw admin UI."""
    repo = clawlab_repo()
    mirrors = [repo / "ssh-ops-mcp" / "ios-xe-policy.yaml"]
    runtime = Path.home() / "ssh_ops_mcp" / "data" / "ios-xe-policy.yaml"
    if runtime.parent.is_dir():
        mirrors.append(runtime)
    return mirrors


def validate_ios_xe_policy(data: object) -> tuple[bool, str]:
    if not isinstance(data, dict):
        return False, "ios-xe-policy.yaml must be a YAML mapping."
    groups = data.get("allow_groups")
    if not isinstance(groups, dict) or not groups:
        return False, "allow_groups must be a non-empty mapping."
    for name, grp in groups.items():
        if not isinstance(grp, dict):
            return False, f"allow_groups.{name} must be a mapping."
        patterns = grp.get("patterns")
        if not isinstance(patterns, list) or not patterns:
            return False, f"allow_groups.{name}.patterns must be a non-empty list."
        access = str(grp.get("access") or "approve").strip().lower()
        if access.replace("-", "_").replace(" ", "_") not in {
            "deny",
            "approve",
            "allow",
            "always_deny",
            "always_allow",
            "approval_required",
            "block",
            "blocked",
        }:
            return False, f"allow_groups.{name}.access has invalid value: {access}"
    always_block = data.get("always_block")
    if always_block is not None and not isinstance(always_block, list):
        return False, "always_block must be a list when present."
    return True, ""


def ios_xe_policy_summary(data: dict) -> dict:
    groups = data.get("allow_groups") or {}
    categories = data.get("group_categories") or []
    cat_labels = {
        str(c.get("id") or ""): str(c.get("label") or c.get("id") or "")
        for c in categories
        if isinstance(c, dict)
    }
    by_category: dict[str, int] = {}
    for name, grp in groups.items():
        if not isinstance(grp, dict):
            continue
        cat = str(grp.get("category") or "other")
        by_category[cat] = by_category.get(cat, 0) + 1
    return {
        "group_count": sum(1 for g in groups.values() if isinstance(g, dict)),
        "always_block_count": len(data.get("always_block") or []),
        "categories": [
            {
                "id": cat_id,
                "label": cat_labels.get(cat_id, cat_id.replace("_", " ").title()),
                "count": count,
            }
            for cat_id, count in sorted(by_category.items())
        ],
    }


def save_ios_xe_policy_content(content: str) -> list[Path]:
    try:
        parsed = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise PolicyError(f"YAML syntax error: {exc}") from exc
    ok, detail = validate_ios_xe_policy(parsed)
    if not ok:
        raise PolicyError(detail)
    normalized = content if content.endswith("\n") else content + "\n"
    seen: set[Path] = set()
    written: list[Path] = []
    for path in [ios_xe_policy_path(), *ios_xe_policy_mirror_paths()]:
        resolved = path.expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        write_text_file(path, normalized)
        written.append(path)
    return written


def merge_ios_xe_policy_rules() -> tuple[bool, str]:
    repo = clawlab_repo()
    script = repo / "admin-access" / "merge-ios-xe-policy.py"
    if not script.is_file():
        return False, f"merge script not found: {script}"
    policy = ios_xe_policy_path()
    if not policy.is_file():
        return False, f"Policy file not found: {policy}"
    rules_dir = rule_pack_dir() / "rules"
    try:
        proc = subprocess.run(
            [
                sys.executable,
                str(script),
                "--rules-dir",
                str(rules_dir),
                "--policy",
                str(policy),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            cwd=str(repo),
        )
    except subprocess.TimeoutExpired:
        return False, "merge-ios-xe-policy.py timed out."
    output = ((proc.stdout or "") + (proc.stderr or "")).strip() or "(no output)"
    return proc.returncode == 0, output
