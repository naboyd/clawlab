#!/usr/bin/env bash
# Render docs/clawlab-policy-enforcement-flow.png from Mermaid source.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO/docs/clawlab-policy-enforcement-flow.mmd"
OUT="$REPO/docs/clawlab-policy-enforcement-flow.png"

if [[ ! -f "$SRC" ]]; then
  echo "Missing source: $SRC" >&2
  exit 1
fi

render_with_npx() {
  npx -y @mermaid-js/mermaid-cli@11 \
    -i "$SRC" -o "$OUT" -b transparent -w 1400 -H 900
}

render_with_docker() {
  podman run --rm -v "$REPO/docs:/docs:Z" docker.io/minio/mermaid-cli:latest \
    -i /docs/clawlab-policy-enforcement-flow.mmd \
    -o /docs/clawlab-policy-enforcement-flow.png \
    -b transparent -w 1400 -H 900
}

echo "==> Rendering $OUT"
if command -v npx >/dev/null 2>&1; then
  render_with_npx
elif command -v podman >/dev/null 2>&1; then
  render_with_docker
else
  echo "Need npx (Node) or podman to render Mermaid." >&2
  echo "Source: $SRC" >&2
  exit 1
fi

echo "Done: $OUT"
