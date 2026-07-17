# Deprecated — use admin-access/alice/

Network specialist v2 merge **included legacy Hannah MCP data** (`training_data_v1.1.1.jsonl`), which hurt OpenClaw ssh-ops benchmarks.

**Use instead:**

```bash
bash admin-access/alice/merge-alice-v1.sh
bash ~/ai/hannai-ops/training/train_alice_remote.sh --all
```

See [../alice/README.md](../alice/README.md).

---

# Hannah network specialist v2 (legacy)

Bundled generators remain here for reference. Prefer `admin-access/alice/` for all new work.

## On icecream (legacy — not recommended for Claw)

```bash
cd ~/clawlab && git pull
bash admin-access/hannah-network-v2/merge-hannah-network-v2.sh
cd ~/ai/hannai-ops/training/specialists
bash train_specialists_remote.sh --specialist network --all
```

## Files

| File | Purpose |
|------|---------|
| `merge-hannah-network-v2.sh` | Legacy merge (includes Hannah base JSONL) |
| `generate_clawlab_ssh_ops_training.py` | Superseded by `alice/generate_ssh_ops_training.py` |
| `bench-cli-crafting/` | Superseded by `alice/bench/` |
