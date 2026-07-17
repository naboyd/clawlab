# Alice baseline benchmarks

Compare **stock Llama 3.1 8B** vs **Alice** (`alice:latest`) before and after training.

## Quick run (icecream)

```bash
cd ~/clawlab && git pull

# 1) Baseline control + stock model (before Alice train)
BENCH_MODELS="llama3.1:8b" bash admin-access/alice/bench/run-baseline.sh

# 2) After train + ollama create alice:latest
BENCH_MODELS="llama3.1:8b alice:latest" bash admin-access/alice/bench/run-baseline.sh

# 3) Optional OpenClaw agent smoke
RUN_AGENT=1 CLAWLAB_MODEL=ollama/alice:latest \
  bash admin-access/alice/bench/run-baseline.sh
```

Outputs land in `bench/scorecards/` (markdown scorecard + JSON + logs).

## CLI crafting only

```bash
bash admin-access/alice/bench/bench-cli-crafting.sh
```

## Scoring

| Result | Meaning |
|--------|---------|
| **pass** | Output matches an `accept` pattern |
| **partial** | Starts with `show` but not in accept list |
| **fail** | Empty, dangerous command, or hits `reject` |
| **error** | Ollama unreachable / timeout |

**Score** = `(pass + 0.5×partial) / total × 100%`

## vs OpenClaw agent benchmark

| Benchmark | Tests |
|-----------|--------|
| **CLI crafting** | NL → correct `show` command string |
| **run-baseline.sh RUN_AGENT=1** | End-to-end tool calls + real ssh-ops |
| **tests/policy-test.sh** | Policy + RBAC with `CLAWLAB_MODEL=ollama/alice:latest` |

Use all three before declaring Alice v1 ready.
