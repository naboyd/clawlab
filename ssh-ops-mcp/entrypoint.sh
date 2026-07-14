#!/bin/sh
# Select the run mode. "gui" (default) starts the Flask config UI; "mcp" starts
# the MCP server on stdio (used by the MCP client via `docker run -i`).
set -e

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
