#!/usr/bin/env bash
# run-baseline.sh — record Alice v1 baseline scorecard (control + CLI + optional agent E2E).
#
# Run BEFORE training (stock llama3.1:8b) and AFTER (alice:latest) with the same script.
#
# Usage (icecream):
#   cd ~/clawlab && git pull
#   bash admin-access/alice/bench/run-baseline.sh
#
# Env:
#   BENCH_MODELS       default "llama3.1:8b alice:latest"
#   RUN_AGENT=1        also run OpenClaw agent smoke tests (needs gateway + ssh-ops)
#   CLAWLAB_MODEL      OpenClaw model id (default ollama/llama3.1:8b or first BENCH model)
#   SCORECARD_OUT      default bench/scorecards/scorecard-YYYYMMDD_HHMMSS.md
#
set -Eeuo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
ALICE_DIR="$(cd "$DIR/.." && pwd)"
REPO="$(cd "$ALICE_DIR/../.." && pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
SCORECARD_DIR="${SCORECARD_DIR:-$DIR/scorecards}"
SCORECARD_OUT="${SCORECARD_OUT:-$SCORECARD_DIR/scorecard-$STAMP.md}"
CLI_JSON="$DIR/results-$STAMP.json"

mkdir -p "$SCORECARD_DIR"

log() { printf '==> %s\n' "$*"; }

HOST="$(hostname -s 2>/dev/null || hostname)"
MODELS="${BENCH_MODELS:-llama3.1:8b alice:latest}"
NUM_CTX="${ALICE_NUM_CTX:-4096}"
RUN_AGENT="${RUN_AGENT:-0}"

log "Alice baseline run ($STAMP)"
log "Host: $HOST"
log "Models: $MODELS"
log ""

log "CLI crafting benchmark..."
python3 "$DIR/bench_cli_crafting.py" \
  --models $MODELS \
  --num-ctx "$NUM_CTX" \
  --json-out "$CLI_JSON" \
  | tee "$SCORECARD_DIR/cli-$STAMP.log"

AGENT_SECTION=""
if [ "$RUN_AGENT" = "1" ]; then
  export PATH="${HOME}/.local/bin:${PATH}"
  AGENT_MODEL="${CLAWLAB_MODEL:-ollama/$(echo "$MODELS" | awk '{print $1}')}"
  AGENT_LOG="$SCORECARD_DIR/agent-$STAMP.log"
  log "OpenClaw agent smoke (model=$AGENT_MODEL)..."
  {
    echo "# Agent smoke $STAMP model=$AGENT_MODEL"
    for prompt in \
      "Use ssh-ops list_hosts and reply with host names only." \
      "On C9300-24P run show vlan id 99 read-only via ssh-ops and summarize."
    do
      echo ""
      echo "## Prompt: $prompt"
      SK="agent:main:alice-baseline-$STAMP-$(date +%s%N)"
      timeout 140 openclaw agent --session-key "$SK" --model "$AGENT_MODEL" -m "$prompt" 2>&1 || true
    done
  } | tee "$AGENT_LOG"
  AGENT_SECTION="
## Agent E2E (OpenClaw + ssh-ops)

- Model: \`$AGENT_MODEL\`
- Log: \`$(basename "$AGENT_LOG")\`
- Prompts: list_hosts; show vlan id 99 on C9300-24P
"
fi

python3 - "$CLI_JSON" "$SCORECARD_OUT" "$STAMP" "$HOST" "$MODELS" "$CLI_JSON" "$AGENT_SECTION" <<'PY'
import json, sys
from pathlib import Path

cli_json, out_path, stamp, host, models, cli_rel, agent_section = sys.argv[1:8]
data = json.loads(Path(cli_json).read_text())
lines = [
    f"# Alice baseline scorecard — {stamp}",
    "",
    f"- **Host:** {host}",
    f"- **Models:** {models}",
    f"- **CLI results JSON:** `{Path(cli_rel).name}`",
    "",
    "## CLI crafting (NL → IOS-XE command)",
    "",
    "| Model | Pass | Partial | Fail | Error | Score |",
    "|-------|------|---------|------|-------|-------|",
]
for model, results in data.items():
    counts = {"pass": 0, "partial": 0, "fail": 0, "error": 0}
    for r in results:
        counts[r["score"]] = counts.get(r["score"], 0) + 1
    score = counts["pass"] + 0.5 * counts["partial"]
    total = len(results) or 1
    pct = 100.0 * score / total
    lines.append(
        f"| {model} | {counts['pass']} | {counts['partial']} | {counts['fail']} | {counts['error']} | {pct:.1f}% |"
    )
lines.extend([
    "",
    "## Success criteria (Alice v1)",
    "",
    "- **Agent E2E:** match or beat stock `llama3.1:8b` on list_hosts + VLAN read (no fake hosts/tool_response)",
    "- **CLI crafting:** ≥ 75% with no legacy tool artifacts",
    "- **Policy harness:** `tests/policy-test.sh` agent sections pass with `CLAWLAB_MODEL=ollama/alice:latest`",
    "",
    agent_section,
    "## Notes",
    "",
    "_Fill in after review: regressions, hallucinations, latency._",
    "",
])
Path(out_path).write_text("\n".join(lines), encoding="utf-8")
print(f"Wrote scorecard: {out_path}")
PY

log ""
log "Scorecard: $SCORECARD_OUT"
log "CLI JSON:  $CLI_JSON"
