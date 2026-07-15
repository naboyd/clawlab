#!/bin/sh
# Select the run mode. "gui" (default) starts the Flask config UI; "mcp" starts
# the MCP server on stdio (used by the MCP client via `docker run -i`).
set -e

if [ -d /data ] && [ ! -f /data/ios-xe-policy.yaml ] && [ -f /app/ios-xe-policy.yaml ]; then
  cp /app/ios-xe-policy.yaml /data/ios-xe-policy.yaml
  chmod 600 /data/ios-xe-policy.yaml 2>/dev/null || true
fi

case "${1:-gui}" in
  gui)
    exec python webgui.py
    ;;
  mcp)
    exec python server.py
    ;;
  *)
    # Anything else: run it verbatim (e.g. `secrets_store.py list`, a shell).
    exec "$@"
    ;;
esac
