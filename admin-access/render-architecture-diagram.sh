#!/usr/bin/env bash
# Render docs/clawlab-policy-enforcement-flow.png
# Prefers Python renderer (reliable); falls back to mermaid-cli when available.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO/docs/clawlab-policy-enforcement-flow.mmd"
OUT="$REPO/docs/clawlab-policy-enforcement-flow.png"
PY="$REPO/admin-access/render-policy-flow-diagram.py"

echo "==> Rendering $OUT"

if [[ -f "$PY" ]]; then
  python3 "$PY"
  exit 0
fi

if [[ ! -f "$SRC" ]]; then
  echo "Missing source: $SRC" >&2
  exit 1
fi

render_with_npx() {
  npx -y @mermaid-js/mermaid-cli@11 \
    -c "$REPO/docs/mermaid-config.json" \
    -i "$SRC" -o "$OUT" -b "#0f1419" -w 2600 -H 1500
}

render_with_docker() {
  podman run --rm -v "$REPO/docs:/docs:Z" ghcr.io/mermaid-js/mermaid-cli/mermaid-cli:latest \
    -c /docs/mermaid-config.json \
    -i /docs/clawlab-policy-enforcement-flow.mmd \
    -o /docs/clawlab-policy-enforcement-flow.png \
    -b "#0f1419" -w 2600 -H 1500
}

if command -v npx >/dev/null 2>&1; then
  render_with_npx
elif command -v podman >/dev/null 2>&1; then
  render_with_docker
else
  echo "Need python3+Pillow ($PY) or npx/podman for Mermaid." >&2
  exit 1
fi

echo "Done: $OUT"
