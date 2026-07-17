#!/usr/bin/env bash
# merge-hannah-network-v2.sh — build hannah-specialist-network-v2 training JSONL on icecream.
#
# Lives in clawlab so `git pull` deploys generators + bundled examples.
# Writes output under hannai-ops training (where Unsloth train scripts expect it).
#
# Usage (on icecream):
#   cd ~/clawlab && git pull
#   bash admin-access/hannah-network-v2/merge-hannah-network-v2.sh
#
# Env:
#   HANNAI_OPS_TRAINING  default ~/ai/hannai-ops/training
#   CLAWLAB_REPO         default ~/clawlab (auto-detected from script location)
#   BASE                 override base Hannah JSONL
#   SKIP_GENERATE=1      use bundled clawlab_ssh_ops_training.jsonl only
#
set -Eeuo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
CLAWLAB_DIR="$REPO/admin-access/hannah-network-v2"
HANNAI_TRAINING="${HANNAI_OPS_TRAINING:-$HOME/ai/hannai-ops/training}"
CLAWLAB_REPO="${CLAWLAB_REPO:-$REPO}"
BASE="${BASE:-training_data_with_gaps.jsonl}"
OUT_DIR="$HANNAI_TRAINING/specialists/network"
OUT="$OUT_DIR/training_data_network_v2.jsonl"
WORK="$CLAWLAB_DIR"

log() { printf '==> %s\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[ -d "$HANNAI_TRAINING" ] || die "HANNAI_OPS_TRAINING not found: $HANNAI_TRAINING"

ensure_base_training_data() {
  local base_path="$HANNAI_TRAINING/$BASE"
  if [ -f "$base_path" ]; then
    BASE="$base_path"
    log "Using base: $BASE"
    return 0
  fi

  warn "Missing $(basename "$BASE") — attempting to build or fall back"
  if [ -f "$HANNAI_TRAINING/merge_gaps_into_training.sh" ] \
     && [ -f "$HANNAI_TRAINING/training_data_v1.1.1.jsonl" ] \
     && [ -f "$HANNAI_TRAINING/training_data_gaps_additions.jsonl" ]; then
    (cd "$HANNAI_TRAINING" && bash merge_gaps_into_training.sh)
    if [ -f "$HANNAI_TRAINING/training_data_with_gaps.jsonl" ]; then
      BASE="$HANNAI_TRAINING/training_data_with_gaps.jsonl"
      log "Built base: $BASE"
      return 0
    fi
  fi

  for fallback in training_data_v1.1.1.jsonl training_data.jsonl; do
    if [ -f "$HANNAI_TRAINING/$fallback" ]; then
      BASE="$HANNAI_TRAINING/$fallback"
      warn "Falling back to $BASE"
      return 0
    fi
  done

  die "No base JSONL under $HANNAI_TRAINING (need training_data_v1.1.1.jsonl or similar)"
}

ensure_base_training_data

SSH_OPS_JSONL="$WORK/clawlab_ssh_ops_training.jsonl"
IOSXE_JSONL="$WORK/iosxe_ssh_ops_converted.jsonl"

if [ "${SKIP_GENERATE:-0}" != "1" ]; then
  log "Generating clawlab ssh-ops examples (CLAWLAB_REPO=$CLAWLAB_REPO)"
  if python3 "$WORK/generate_clawlab_ssh_ops_training.py" \
      --clawlab-repo "$CLAWLAB_REPO" \
      -o "$SSH_OPS_JSONL"; then
    :
  else
    warn "Generator failed — using bundled $SSH_OPS_JSONL if present"
  fi

  log "Converting IOS-XE JSONL from $HANNAI_TRAINING/field_definitions/"
  export HANNAI_OPS_TRAINING="$HANNAI_TRAINING"
  if compgen -G "$HANNAI_TRAINING/field_definitions/ios_xe_routing_and_cli_format_*.jsonl" >/dev/null; then
    python3 "$WORK/convert_iosxe_to_ssh_ops.py" -o "$IOSXE_JSONL" || warn "IOS-XE conversion failed"
  else
    warn "No ios_xe_routing_and_cli_format_*.jsonl on icecream — skipping"
    : > "$IOSXE_JSONL"
  fi
else
  log "SKIP_GENERATE=1 — using bundled clawlab_ssh_ops_training.jsonl"
  : > "$IOSXE_JSONL"
fi

[ -f "$SSH_OPS_JSONL" ] || die "Missing $SSH_OPS_JSONL (git pull clawlab for admin-access/hannah-network-v2/)"

mkdir -p "$OUT_DIR"
log "Merging -> $OUT"
{
  cat "$BASE"
  cat "$SSH_OPS_JSONL"
  [ -s "$IOSXE_JSONL" ] && cat "$IOSXE_JSONL"
} > "$OUT"

lines="$(wc -l < "$OUT" | tr -d ' ')"
log "Merged $lines rows (base: $(basename "$BASE"))"
log ""
log "Next on icecream:"
log "  cd ~/ai/hannai-ops/training/specialists"
log "  bash train_specialists_remote.sh --specialist network --all"
log "  bash ../add-model-to-system.sh --path network/hannah-specialist-network-v2_merged_16bit --system ollama"
