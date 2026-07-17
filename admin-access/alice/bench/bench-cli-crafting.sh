#!/usr/bin/env bash
# bench-cli-crafting.sh — Alice baseline: NL → IOS-XE CLI (no MCP execution).
#
#   cd ~/clawlab && git pull
#   bash admin-access/alice/bench/bench-cli-crafting.sh
#
set -Eeuo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
OUT="${DIR}/results-$(date +%Y%m%d_%H%M%S).json"

MODELS="${BENCH_MODELS:-llama3.1:8b alice:latest}"
NUM_CTX="${ALICE_NUM_CTX:-4096}"

echo "Models: $MODELS"
echo "num_ctx: $NUM_CTX"
echo "Results: $OUT"
echo ""

python3 "$DIR/bench_cli_crafting.py" \
  --models $MODELS \
  --num-ctx "$NUM_CTX" \
  --json-out "$OUT"
