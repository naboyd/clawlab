# Hannah network specialist v2 (clawlab / OpenClaw + ssh-ops)

Bundled in **clawlab** so icecream gets generators via `git pull` (no separate hannai-ops sync required for these scripts).

## On icecream

```bash
cd ~/clawlab && git pull

bash admin-access/hannah-network-v2/merge-hannah-network-v2.sh

cd ~/ai/hannai-ops/training/specialists
bash train_specialists_remote.sh --specialist network --all
```

Output: `~/ai/hannai-ops/training/specialists/network/training_data_network_v2.jsonl`

## Files

| File | Purpose |
|------|---------|
| `merge-hannah-network-v2.sh` | Orchestrator (run this) |
| `generate_clawlab_ssh_ops_training.py` | Regenerate from `ssh-ops-mcp/server.py` |
| `convert_iosxe_to_ssh_ops.py` | IOS-XE captures → `run_command` format |
| `clawlab_ssh_ops_training.jsonl` | Bundled 10 examples (works offline) |

## OpenClaw after train

```bash
openclaw config set agents.defaults.model.primary 'ollama/hannah-specialist-network-v2:latest'
systemctl --user restart openclaw-gateway
```
