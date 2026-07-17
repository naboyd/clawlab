#!/usr/bin/env bash
# merge-alice-v1.sh — build Alice v1 training JSONL (ssh-ops ONLY, no Hannah legacy MCP).
#
# Canonical data generators live in clawlab. Output is written under hannai-ops
# training/ where Unsloth scripts expect it.
#
# Usage (on icecream):
#   cd ~/clawlab && git pull
#   bash admin-access/alice/merge-alice-v1.sh
#
# Env:
#   HANNAI_OPS_TRAINING  default ~/ai/hannai-ops/training
#   CLAWLAB_REPO         default auto-detect from script location
#   SKIP_GENERATE=1      use bundled training/bundled/*.jsonl only
#
set -Eeuo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
ALICE_DIR="$REPO/admin-access/alice"
HANNAI_TRAINING="${HANNAI_OPS_TRAINING:-$HOME/ai/hannai-ops/training}"
CLAWLAB_REPO="${CLAWLAB_REPO:-$REPO}"
OUT_DIR="$HANNAI_TRAINING/specialists/alice"
OUT="$OUT_DIR/alice_ssh_ops_v1.jsonl"
WORK="$ALICE_DIR"

log() { printf '==> %s\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[ -d "$HANNAI_TRAINING" ] || die "HANNAI_OPS_TRAINING not found: $HANNAI_TRAINING"

SSH_OPS_JSONL="$WORK/training/ssh_ops_generated.jsonl"
IOSXE_JSONL="$WORK/training/iosxe_ssh_ops_converted.jsonl"
NEGATIVES="$WORK/training/alice_negatives.jsonl"
BUNDLED_SSH="$WORK/training/bundled/ssh_ops_generated.jsonl"
BUNDLED_IOSXE="$WORK/training/bundled/iosxe_ssh_ops_converted.jsonl"

if [ "${SKIP_GENERATE:-0}" != "1" ]; then
  log "Generating Alice ssh-ops examples (CLAWLAB_REPO=$CLAWLAB_REPO)"
  mkdir -p "$WORK/training"
  if python3 "$WORK/generate_ssh_ops_training.py" \
      --clawlab-repo "$CLAWLAB_REPO" \
      -o "$SSH_OPS_JSONL"; then
    :
  else
    warn "Generator failed — using bundled $(basename "$BUNDLED_SSH") if present"
    [ -f "$BUNDLED_SSH" ] && cp "$BUNDLED_SSH" "$SSH_OPS_JSONL"
  fi

  log "Converting IOS-XE JSONL from $HANNAI_TRAINING/field_definitions/"
  export HANNAI_OPS_TRAINING="$HANNAI_TRAINING"
  if compgen -G "$HANNAI_TRAINING/field_definitions/ios_xe_routing_and_cli_format_*.jsonl" >/dev/null; then
    python3 "$WORK/convert_iosxe_to_ssh_ops.py" -o "$IOSXE_JSONL" || warn "IOS-XE conversion failed"
  elif [ -s "$BUNDLED_IOSXE" ]; then
    warn "No ios_xe_routing_and_cli_format_*.jsonl on host — using bundled $(basename "$BUNDLED_IOSXE")"
    cp "$BUNDLED_IOSXE" "$IOSXE_JSONL"
    log "Bundled IOS-XE rows: $(wc -l < "$IOSXE_JSONL" | tr -d ' ')"
  else
    warn "No IOS-XE source and no bundled conversion — skipping IOS-XE rows"
  fi
else
  log "SKIP_GENERATE=1 — using bundled training files"
  mkdir -p "$WORK/training"
  [ -f "$BUNDLED_SSH" ] && cp "$BUNDLED_SSH" "$SSH_OPS_JSONL"
  [ -f "$BUNDLED_IOSXE" ] && cp "$BUNDLED_IOSXE" "$IOSXE_JSONL"
fi

[ -f "$SSH_OPS_JSONL" ] || die "Missing $SSH_OPS_JSONL (git pull clawlab admin-access/alice/)"

mkdir -p "$OUT_DIR"
log "Merging ssh-ops-only -> $OUT"
{
  cat "$SSH_OPS_JSONL"
  [ -f "$NEGATIVES" ] && cat "$NEGATIVES"
  [ -s "$IOSXE_JSONL" ] && cat "$IOSXE_JSONL"
} > "$OUT"

lines="$(wc -l < "$OUT" | tr -d ' ')"
ssh_lines="$(wc -l < "$SSH_OPS_JSONL" | tr -d ' ')"
neg_lines="$([ -f "$NEGATIVES" ] && wc -l < "$NEGATIVES" | tr -d ' ' || echo 0)"
iosxe_lines="$([ -s "$IOSXE_JSONL" ] && wc -l < "$IOSXE_JSONL" | tr -d ' ' || echo 0)"

log "Merged $lines rows (ssh_ops=$ssh_lines negatives=$neg_lines iosxe=$iosxe_lines)"
log "Excluded: training_data_v1.1.1.jsonl and all legacy ios_get_* MCP rows"
log ""
log "Next on icecream:"
log "  cd ~/ai/hannai-ops/training"
log "  bash train_alice_remote.sh --all"
log "  # or locally on icecream after merge:"
log "  cd specialists/alice && python3 ../../train_unsloth_optimized.py \\"
log "    --model-family llama3.1 --model 8b --data alice_ssh_ops_v1.jsonl --output alice"
log "  bash ../../add-model-to-system.sh --path specialists/alice/alice_merged_16bit --system ollama --name alice:latest"
