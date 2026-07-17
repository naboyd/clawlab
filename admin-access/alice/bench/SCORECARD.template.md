# Alice baseline scorecard — YYYY-MM-DD_HHMMSS

- **Host:** icecream
- **Models:** llama3.1:8b alice:latest
- **CLI results JSON:** `results-....json`

## CLI crafting (NL → IOS-XE command)

| Model | Pass | Partial | Fail | Error | Score |
|-------|------|---------|------|-------|-------|
| llama3.1:8b | | | | | |
| alice:latest | | | | | |

## Agent E2E (OpenClaw + ssh-ops)

| Check | llama3.1:8b | alice:latest |
|-------|-------------|--------------|
| list_hosts returns real inventory | | |
| show vlan id 99 on C9300-24P | | |
| No fake `<tool_response>` / ios_* tools | | |

## Policy harness

```bash
RUN_AGENT=1 CLAWLAB_MODEL=ollama/llama3.1:8b bash ~/clawlab/tests/policy-test.sh
RUN_AGENT=1 CLAWLAB_MODEL=ollama/alice:latest bash ~/clawlab/tests/policy-test.sh
```

| Result | llama3.1:8b | alice:latest |
|--------|-------------|--------------|
| policy-test.sh | | |

## Success criteria (Alice v1)

- Agent E2E: match or beat stock `llama3.1:8b`
- CLI crafting: ≥ 75%
- No legacy MCP tool names in agent output

## Notes

_Reviewer observations, latency, regressions._
