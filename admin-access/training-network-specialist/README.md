# Maintainer training tooling (optional)

Scripts to generate ssh-ops MCP tool-calling training JSONL from synthetic
examples or sanitized IOS-XE captures.

**Not required** to install or run clawlab. Generated `.jsonl` files are
gitignored because they may contain lab-specific hostnames or command output.

```bash
cd admin-access/training-network-specialist
python3 generate_clawlab_ssh_ops_training.py
python3 convert_iosxe_to_ssh_ops.py   # optional, if you have sanitized captures
```

Use generic hostnames (`lab.example.com`, `192.168.1.x`) in any captures you
commit or share.
