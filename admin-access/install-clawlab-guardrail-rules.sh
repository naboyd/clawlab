#!/usr/bin/env bash
# Install Clawlab guardrail rule extensions into the active DefenseClaw strict pack.
# Merges into commands.yaml + local-patterns.yaml (separate category files are
# overwritten alphabetically by commands.yaml and never take effect).
#
# Usage:
#   bash admin-access/install-clawlab-guardrail-rules.sh
#   RULE_PACK_DIR=~/.defenseclaw/policies/guardrail/strict bash ...
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${REPO}/config-templates/guardrail-rules"
DC_HOME="${DEFENSECLAW_HOME:-$HOME/.defenseclaw}"
PY="${CLAW_PYTHON:-python3}"

PACK_DIR="${RULE_PACK_DIR:-}"
if [ -z "$PACK_DIR" ] && [ -f "${DC_HOME}/config.yaml" ]; then
  PACK_DIR="$(grep -E '^\s*rule_pack_dir:' "${DC_HOME}/config.yaml" | head -1 \
    | sed -E 's/^[[:space:]]*rule_pack_dir:[[:space:]]*//' | tr -d "\"'" \
    | sed "s|^~|$HOME|")"
fi
PACK_DIR="${PACK_DIR:-$DC_HOME/policies/guardrail/strict}"
RULES_DIR="${PACK_DIR}/rules"
mkdir -p "$RULES_DIR"

"$PY" "${REPO}/admin-access/merge-clawlab-guardrail-rules.py" \
  --rules-dir "$RULES_DIR" \
  --src-dir "$SRC"

"$PY" "${REPO}/admin-access/sync-ios-xe-policy.py"

"$PY" "${REPO}/admin-access/merge-ios-xe-policy.py" \
  --rules-dir "$RULES_DIR" \
  --policy "${REPO}/config-templates/ios-xe-policy.yaml"

reload_gateway() {
  # Rule-pack YAML edits do NOT hot-reload; the inspect API (port 18970) is
  # served by the defenseclaw-gateway sidecar, not openclaw-gateway.service.
  if command -v defenseclaw-gateway >/dev/null 2>&1; then
    if defenseclaw-gateway restart 2>/dev/null; then
      echo "Reloaded guardrail via defenseclaw-gateway restart"
      sleep 2
      return 0
    fi
  fi
  if systemctl --user restart openclaw-gateway.service 2>/dev/null; then
    echo "Reloaded openclaw-gateway (if inspect still allows useradd, run: defenseclaw-gateway restart)"
    sleep 2
    return 0
  fi
  echo "NOTE: restart the DefenseClaw sidecar to load merged rules:"
  echo "  defenseclaw-gateway restart"
  return 1
}

verify_useradd_block() {
  local token="" action="" f key val
  for f in \
    "${DC_HOME}/shims/.token" \
    "${DC_HOME}/.env" \
    "$HOME/.openclaw/gateway.systemd.env"; do
    [ -f "$f" ] || continue
    for key in DEFENSECLAW_GATEWAY_TOKEN OPENCLAW_GATEWAY_TOKEN; do
      val="$(grep -E "^${key}=" "$f" 2>/dev/null | head -1 | cut -d= -f2- | tr -d "\"'")" || true
      if [ -n "$val" ]; then
        token="$val"
        break 2
      fi
    done
  done
  [ -n "$token" ] || return 0
  action="$(curl -s -m8 -X POST "http://127.0.0.1:18970/api/v1/inspect/tool" \
    -H "Authorization: Bearer ${token}" \
    -H 'Content-Type: application/json' \
    -d '{"tool":"bash","args":{"command":"useradd clawlab-verify"}}' \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('action','err'))" 2>/dev/null || echo err)"
  if [ "$action" = "block" ]; then
    echo "Verify: inspect-tool useradd -> block (rules active in memory)"
  else
    echo "WARN: inspect-tool useradd -> ${action} (rules on disk but sidecar not reloaded)"
    echo "      Run: defenseclaw-gateway restart"
    return 1
  fi
}

reload_gateway || true
verify_useradd_block || true

echo "Done. Verify with:"
echo "  defenseclaw-gateway restart   # required after manual YAML edits"
echo "  defenseclaw guardrail status"
echo "  grep -E 'CMD-USERADD|create a local user' ${RULES_DIR}/commands.yaml ${RULES_DIR}/local-patterns.yaml"
echo "  ./tests/policy-test.sh --no-agent"
