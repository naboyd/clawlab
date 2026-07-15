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

reload_gateway() {
  if systemctl --user restart openclaw-gateway.service 2>/dev/null; then
    echo "Reloaded guardrail via openclaw-gateway.service"
    return 0
  fi
  if command -v defenseclaw-gateway >/dev/null 2>&1; then
    if defenseclaw-gateway restart 2>/dev/null; then
      echo "Reloaded guardrail via defenseclaw-gateway restart"
      return 0
    fi
  fi
  echo "NOTE: restart openclaw-gateway to load new rules:"
  echo "  systemctl --user restart openclaw-gateway"
  return 1
}

reload_gateway || true

echo "Done. Verify with:"
echo "  defenseclaw guardrail status"
echo "  grep -E 'CMD-USERADD|create a local user' ${RULES_DIR}/commands.yaml ${RULES_DIR}/local-patterns.yaml"
echo "  ./tests/policy-test.sh --no-agent"
