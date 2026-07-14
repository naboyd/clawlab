# Policy test harness

`policy-test.sh` exercises every enforcement layer around the OpenClaw agent with
paired in-policy (expect **allow**) and out-of-policy (expect **block**) cases, and
asserts on the outcome (exit non-zero on any failure).

Layers covered:
1. **DefenseClaw C2/exfil rules** via the sidecar inspect-tool API — public curl
   (allow) vs `/etc/shadow` exfil, `nc -e`, and `bash /dev/tcp` reverse shells (block).
2. **ssh-ops MCP read-only allowlist** — `uptime`/`df` (allow) vs `rm`/command
   chaining (block).
3. **DefenseClaw tool-level block list** — `tool block`/`unblock` round-trip.
4. **Agent-driven end-to-end** — `openclaw agent` reads diagnostics via the MCP
   (in-policy), and reads a planted injection canary that it must flag, not execute
   (out-of-policy). Prints recent DefenseClaw audit detections.

## Run

```bash
./policy-test.sh            # full run (includes the ~2 slow agent turns)
./policy-test.sh --no-agent # fast: deterministic direct probes only
```

Env: `CLAWLAB_HOST` (default `icecream`), `CLAWLAB_MODEL` (default
`anthropic/claude-sonnet-5` — must be a tool-capable model). Credentials
are auto-discovered locally and never printed.

Latest run: **12/12 PASS**.
