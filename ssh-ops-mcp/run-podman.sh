#!/usr/bin/env bash
# Build the image and run the ssh-ops config GUI with rootless Podman.
# The MCP server itself is launched on-demand by your client / agent via
# `podman run -i` (see README), not by this script.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
mkdir -p data

echo ">> building image (ssh-ops:latest)"
podman build -t ssh-ops:latest .

echo ">> (re)starting GUI container"
podman rm -f ssh-ops-gui >/dev/null 2>&1 || true
podman run --rm -d --name ssh-ops-gui \
  -p 127.0.0.1:8765:8765 \
  -v "$DIR/data:/data:Z" \
  -v "$HOME/.ssh:/root/.ssh:ro,Z" \
  ssh-ops:latest gui

echo ">> GUI running at http://127.0.0.1:8765"
echo ">> logs: podman logs -f ssh-ops-gui"
