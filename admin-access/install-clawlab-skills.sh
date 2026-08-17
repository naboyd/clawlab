#!/usr/bin/env bash
# Symlink clawlab OpenClaw skills into the agent workspace.
#
#   bash admin-access/install-clawlab-skills.sh
set -Eeuo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
OC_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"
WS="${CLAW_OPENCLAW_WORKSPACE:-$OC_HOME/workspace}"
SKILLS_DST="$WS/skills"

say() { printf '>> %s\n' "$*"; }

[[ -d "$REPO/skills" ]] || {
  echo "error: missing $REPO/skills" >&2
  exit 1
}

mkdir -p "$SKILLS_DST"
linked=0
for skill_dir in "$REPO"/skills/*/; do
  [[ -d "$skill_dir" ]] || continue
  [[ -f "$skill_dir/SKILL.md" ]] || continue
  name="$(basename "$skill_dir")"
  ln -sfn "$skill_dir" "$SKILLS_DST/$name"
  say "Linked skill: $name → $SKILLS_DST/$name"
  linked=$((linked + 1))
done

if [[ "$linked" -eq 0 ]]; then
  echo "warn: no skills linked under $REPO/skills" >&2
  exit 1
fi

say "OpenClaw workspace skills: $SKILLS_DST"
say "Restart gateway if running: systemctl --user restart openclaw-gateway"
say "  or: bash install/local-full-ctl.sh restart"
