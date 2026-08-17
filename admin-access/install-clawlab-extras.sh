#!/usr/bin/env bash
# Optional clawlab add-ons: OpenClaw skills + IOS config archive/drift timer.
#
# Called from install-clawstack.sh (local-full / local / server) and install-portals.sh.
#
#   bash admin-access/install-clawlab-extras.sh
#   bash admin-access/install-clawlab-extras.sh --skills-only
#   bash admin-access/install-clawlab-extras.sh --ios-archive-only
set -Eeuo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SKILLS_ONLY=0
IOS_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skills-only) SKILLS_ONLY=1 ;;
    --ios-archive-only) IOS_ONLY=1 ;;
    -h|--help)
      sed -n '1,12p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
  shift
done

run_skills=1
run_ios=1
[[ "$SKILLS_ONLY" -eq 1 ]] && run_ios=0
[[ "$IOS_ONLY" -eq 1 ]] && run_skills=0

if [[ "$run_skills" -eq 1 ]]; then
  bash "$REPO/admin-access/install-clawlab-skills.sh"
fi

if [[ "$run_ios" -eq 1 ]]; then
  bash "$REPO/admin-access/install-ios-config-archive.sh"
fi
