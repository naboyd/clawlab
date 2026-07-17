#!/usr/bin/env bash
# local-full-doctor.sh — Mac local-full policy prerequisites (works without ctl doctor subcommand)
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=lib/clawlab-local-full.sh
source "$SCRIPT_DIR/lib/clawlab-local-full.sh"
clawlab_local_full_doctor "$REPO"
