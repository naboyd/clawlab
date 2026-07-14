#!/usr/bin/env bash
# Re-apply DefenseClaw exec-shim hardening: inspect the FULL command (incl. the
# tool name) so rules keyed on "<tool> <flag>" (e.g. CMD-REVSHELL-NC = "nc -e")
# match. DefenseClaw regenerates these shims with cmd="$*" (tool name dropped);
# this restores cmd="<tool> $*". Idempotent — only writes when needed.
set -euo pipefail
SHIMS="${DEFENSECLAW_SHIMS:-$HOME/.defenseclaw/shims}"
changed=0
for f in curl nc wget ssh npm pip; do
  p="$SHIMS/$f"
  [ -f "$p" ] && [ ! -L "$p" ] || continue
  tool=$(grep -oP -- '--arg tool "\K[^"]+' "$p" | head -1 || true); [ -n "$tool" ] || tool="$f"
  if grep -qF -- "--arg cmd \"\$*\"" "$p"; then
    python3 - "$p" "$tool" <<'PY'
import sys
p,tool=sys.argv[1],sys.argv[2]
s=open(p).read().replace('--arg cmd "$*"', f'--arg cmd "{tool} $*"')
open(p,'w').write(s)
PY
    echo "$(date -Is) shim-heal: hardened $f (tool=$tool)"; changed=1
  fi
done
[ "$changed" = 1 ] || echo "$(date -Is) shim-heal: shims already hardened"
