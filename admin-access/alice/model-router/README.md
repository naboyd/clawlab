# clawlab-model-router (sketch — not implemented)

Future OpenClaw plugin to route user messages to the right local SLM before each agent turn.

## Phase 0 (current)

No plugin. Fixed primary:

```bash
openclaw config set agents.defaults.model.primary 'ollama/alice:latest'
```

## Phase 1 (log-only router)

1. User message arrives at OpenClaw gateway.
2. Plugin calls Ollama `tool-selector-v5` (or `alice-router-v1` when trained).
3. Classifier returns `{ "domain": "network", "confidence": 0.92 }`.
4. Plugin **always** uses `alice:latest` but logs domain + confidence for tuning.

## Phase 2 (multi-model)

Use `model_registry.json.example`:

- `network` → `alice:latest`
- `splunk` → `alice-splunk:latest` (when trained)
- `general` + low confidence → `llama3.1:8b` or Claude fallback

Implementation options:

| Option | Pros | Cons |
|--------|------|------|
| OpenClaw plugin hook | Native per-turn model override | Requires OpenClaw hook API |
| Wrapper script | Simple: `clawlab-agent.sh "prompt"` | Bypasses Control UI |
| Hannah Gradio orchestrator | Reuses tool-selector today | Two systems |

## Fallback chain

On empty response, tool-call parse failure, or router confidence &lt; threshold:

```
alice:latest → llama3.1:8b → anthropic/claude-sonnet-5
```

## Do not build until

Alice v1 **matches or beats** stock `llama3.1:8b` on `bench/run-baseline.sh` agent smoke tests.

## Related

- Alice training: `../README.md`
- Hannah tool-selector (tools, not models): `hannai-ops/services/tool_selector.py`
