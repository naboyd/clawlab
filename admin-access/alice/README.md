# Alice — clawlab OpenClaw agent model (ssh-ops)

**Alice** is the fine-tuned local model for **OpenClaw + ssh-ops MCP** on icecream.
Training data is **ssh-ops only** — no legacy Hannah `ios_get_*` rows.

> **Naming:** Ollama tag `alice:latest` is the model. The claw-auth user `alice` (operator role) is unrelated.

## Layout

| Path | Purpose |
|------|---------|
| `merge-alice-v1.sh` | Build `alice_ssh_ops_v1.jsonl` (ssh-ops + negatives + IOS-XE) |
| `generate_ssh_ops_training.py` | Hand-crafted tool-calling examples from `ssh-ops-mcp/server.py` |
| `convert_iosxe_to_ssh_ops.py` | IOS-XE captures → `run_command` format |
| `training/alice_negatives.jsonl` | Anti-hallucination / no legacy MCP tools |
| `training/bundled/` | Offline fallbacks when generators cannot run |
| `bench/` | Baselines vs stock `llama3.1:8b` |
| `model-router/` | Future plugin sketch (not implemented) |

GPU train/export scripts stay in **hannai-ops** (`training/train_alice_remote.sh`).

## On icecream — full pipeline

```bash
cd ~/clawlab && git pull
cd ~/ai/hannai-ops && git pull   # training scripts

# 1) Baseline BEFORE train (record scorecard)
BENCH_MODELS="llama3.1:8b" bash ~/clawlab/admin-access/alice/bench/run-baseline.sh

# 2) Merge training data (ssh-ops only)
bash ~/clawlab/admin-access/alice/merge-alice-v1.sh

# 3) Train + register Ollama model
cd ~/ai/hannai-ops/training
bash train_alice_remote.sh --all

# 4) Point OpenClaw at Alice
export PATH="$HOME/.local/bin:$PATH"
openclaw config set agents.defaults.model.primary 'ollama/alice:latest'
systemctl --user restart openclaw-gateway

# 5) Baseline AFTER train
BENCH_MODELS="llama3.1:8b alice:latest" RUN_AGENT=1 CLAWLAB_MODEL=ollama/alice:latest \
  bash ~/clawlab/admin-access/alice/bench/run-baseline.sh
```

## Train locally on icecream (no SSH from Mac)

```bash
bash ~/clawlab/admin-access/alice/merge-alice-v1.sh
cd ~/ai/hannai-ops/training/specialists/alice
source ~/unsloth_env/bin/activate
python3 ../../train_unsloth_optimized.py \
  --model-family llama3.1 --model 8b \
  --data alice_ssh_ops_v1.jsonl \
  --output alice \
  --epochs 3 --max-length 512 --batch-size 1 --grad-accum 4
bash ../../add-model-to-system.sh \
  --path "$(pwd)/alice_merged_16bit" --system ollama --name alice:latest
```

## Data policy (Alice v1)

**Included:**

- `list_hosts`, `run_command`, `propose_change`, `check_health` multi-turn examples
- IOS-XE CLI → ssh-ops conversion (when `field_definitions/` present)
- Negative rows (no fake tool output, no `ios_*` legacy tools)

**Excluded:**

- `training_data_v1.1.1.jsonl` and Hannah multi-MCP rows
- WLC / ISE / Splunk / AD unless rewritten for ssh-ops

## Base model

**Llama 3.1 8B Instruct** — best agent ssh-ops baseline in prior tests. Train from a **fresh** base, not an existing Hannah merged checkpoint.

## Success criteria

| Test | Target |
|------|--------|
| OpenClaw agent E2E | ≥ stock `llama3.1:8b`; no fake hosts |
| CLI crafting bench | ≥ 75% |
| `tests/policy-test.sh` | Pass with `CLAWLAB_MODEL=ollama/alice:latest` |

## Deprecated path

`admin-access/hannah-network-v2/` merged legacy Hannah data — do not use for Alice. See that README for migration notes.
