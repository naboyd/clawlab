#!/usr/bin/env bash
# doctor.sh — ssh-ops Podman stack diagnostics (GUI + MCP)
set -Eeuo pipefail

_SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA_DIR="${SSH_OPS_DATA:-$HOME/.clawlab/ssh-ops/data}"
LEGACY_DATA="${SSH_OPS_LEGACY_DATA:-$HOME/ssh_ops_mcp/data}"
LOG_DIR="${SSH_OPS_LOG_DIR:-$HOME/.clawlab/ssh-ops/logs}"

fail=0
warn() { echo "WARN: $*"; }
err() { echo "FAIL: $*"; fail=1; }
ok() { echo "OK:   $*"; }

echo "=== ssh-ops doctor ==="
echo "time: $(date -Is)"
echo "data: $DATA_DIR"
echo

echo "--- data files ---"
if [[ ! -d "$DATA_DIR" ]]; then
  err "data directory missing: $DATA_DIR"
else
  ok "data directory exists"
  for f in hosts.yaml .env master.key; do
    if [[ -f "$DATA_DIR/$f" ]]; then
      ok "$f present"
    else
      err "$f missing in $DATA_DIR (MCP will crash-loop without hosts.yaml)"
      if [[ -f "$LEGACY_DATA/$f" ]]; then
        warn "found $f in legacy path $LEGACY_DATA — copy or set SSH_OPS_DATA=$LEGACY_DATA"
      fi
    fi
  done
  if [[ -f "$DATA_DIR/hosts.yaml" ]]; then
    hosts_n="$(grep -c '^[[:space:]]*[A-Za-z0-9_.-]\+:' "$DATA_DIR/hosts.yaml" 2>/dev/null || echo 0)"
    echo "     hosts.yaml host keys (approx): $hosts_n"
  fi
fi
echo

echo "--- podman containers ---"
if ! command -v podman >/dev/null 2>&1; then
  warn "podman not on PATH"
else
  for name in ssh-ops-gui ssh-ops-mcp; do
    if podman ps --format '{{.Names}}' 2>/dev/null | grep -qx "$name"; then
      status="$(podman ps --filter "name=^${name}$" --format '{{.Status}}')"
      ok "$name running ($status)"
      if [[ "$name" == "ssh-ops-mcp" ]] && [[ "$status" == Up*second* ]]; then
        warn "$name may be crash-looping (uptime only seconds)"
      fi
    elif podman ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "$name"; then
      err "$name exists but not running"
      echo "     last log lines:"
      podman logs --tail 5 "$name" 2>&1 | sed 's/^/       /'
    else
      warn "$name container not found (run: CLAWLAB_MANAGE_MCP=1 ./podctl.sh)"
    fi
  done
fi
echo

echo "--- loopback health ---"
if curl -fsS "http://127.0.0.1:8765/healthz" >/dev/null 2>&1; then
  ok "GUI healthz :8765"
else
  err "GUI healthz http://127.0.0.1:8765/healthz"
fi
if curl -fsS "http://127.0.0.1:8766/" >/dev/null 2>&1; then
  ok "MCP listener :8766"
elif podman ps --filter "name=^ssh-ops-mcp$" --format '{{.Status}}' 2>/dev/null | grep -qE 'Up ([2-9]|[1-9][0-9]+) (minute|hour|day)'; then
  ok "MCP container stable (streamable-http may not answer GET /)"
elif podman logs --tail 20 ssh-ops-mcp 2>/dev/null | grep -qE 'Uvicorn running|Application startup complete'; then
  ok "MCP process started (see podman logs ssh-ops-mcp)"
else
  err "MCP not healthy on :8766 — check: podman logs ssh-ops-mcp"
fi
echo

echo "--- recent MCP errors ---"
if command -v podman >/dev/null 2>&1 && podman container exists ssh-ops-mcp 2>/dev/null; then
  if podman logs --tail 30 ssh-ops-mcp 2>&1 | grep -q "Config not found at /data/hosts.yaml"; then
    err "MCP log shows missing /data/hosts.yaml — sync data dir (see above)"
  elif podman logs --tail 30 ssh-ops-mcp 2>&1 | grep -q "No module named 'ios_config_archive'"; then
    err "MCP image missing ios_config_archive.py — rebuild: podman build -t ssh-ops:latest $PWD && CLAWLAB_MANAGE_MCP=1 ./podctl.sh --recreate"
  else
    ok "no recent hosts.yaml FileNotFoundError in MCP logs"
  fi
fi
echo

echo "--- logs ---"
if [[ -f "$LOG_DIR/pods.log" ]]; then
  echo "tail $LOG_DIR/pods.log:"
  tail -n 8 "$LOG_DIR/pods.log" | sed 's/^/  /'
else
  warn "no combined log at $LOG_DIR/pods.log"
fi
echo

if [[ "$fail" -eq 0 ]]; then
  echo "Done — no critical issues."
else
  echo "Done — fix FAIL items above, then: CLAWLAB_MANAGE_MCP=1 ./podctl.sh --recreate"
  exit 1
fi
