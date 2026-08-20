---
name: thousandeyes
description: >
  Query Cisco ThousandEyes via the hosted MCP at api.thousandeyes.com — tests,
  alerts, events, outages, and on-demand instant tests. Use when the user asks
  about ThousandEyes monitoring, application or network path visibility, active
  alerts, outages, test results, or WAN/cloud performance.
---

# Cisco ThousandEyes MCP

Read-heavy network and application observability through OpenClaw's
`mcp.servers.thousandeyes` entry (hosted SaaS — not the lab ssh-ops proxy).

## Prerequisites

- ThousandEyes subscription with **API Access** on the token user's role
- Lab host configured: `bash admin-access/configure-openclaw-thousandeyes-mcp.sh`
- OpenClaw gateway restarted after config changes

## When to use

| User intent | Start with |
|-------------|------------|
| "Any active alerts?" | List alerts → get details for critical items |
| "Outages last 24h?" | Search outages with time filter |
| "What tests run to X?" | List tests → get test details |
| "Events around 3pm?" | List events in time range |
| "Run HTTP test from Seattle" | Instant test tools (confirm with user first) |

## Tool usage guidelines

1. **Prefer read-only tools first** — list/get tests, events, alerts, outages.
2. **Instant tests change state** — confirm target URL, agents, and test type with
   the user before running or rerunning instant tests.
3. **Be selective** — Cisco recommends enabling only needed tools; avoid chaining
   many TE calls in one turn (timeouts under load).
4. **Correlate with lab ops** — for device config or CLI, use **ssh-ops** MCP, not
   ThousandEyes. TE shows path/app performance; ssh-ops applies gated changes.

## Common flows

### Alert triage

1. List active alerts
2. Get alert details for severity / affected targets
3. Cross-check list events for the same window
4. Summarize: what, where (agents/locations), since when

### Outage investigation

1. Search outages (last N hours / named app or network)
2. Get event or alert details for the outage ID
3. If path-related, list tests touching the target and pull test details

### Instant troubleshooting

Only after user confirms:

1. Run instant test (HTTP, network, etc.) from named agents
2. Retrieve instant test results by ID
3. Present latency, loss, and path data; do not mutate lab network gear from TE alone

## Auth and secrets

- Token lives in `~/.clawlab/thousandeyes/env` (not in git)
- Rotate: `bash admin-access/rotate-openclaw-thousandeyes-token.sh`
- Remove MCP entry: `bash admin-access/configure-openclaw-thousandeyes-mcp.sh --remove`

## ThousandEyes for Government

Some tools are unavailable on TE-Gov instances. If tools fail with permission or
feature errors, note the tenant type and stick to supported read APIs.

## Related clawlab tools

| Need | MCP server |
|------|------------|
| IOS config, DHCP, SSH | ssh-ops (`:8767` identity proxy) |
| Prompt/tool policy | DefenseClaw |
| Config drift vs change log | ios-config-drift skill + ssh-ops |
