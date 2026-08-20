#!/usr/bin/env bash
# Rotate ThousandEyes API token in ~/.clawlab/thousandeyes/env and openclaw.json.
#
# Usage:
#   THOUSANDEYES_API_TOKEN=… bash admin-access/rotate-openclaw-thousandeyes-token.sh
set -Eeuo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
exec bash "$REPO/admin-access/configure-openclaw-thousandeyes-mcp.sh" "$@"
