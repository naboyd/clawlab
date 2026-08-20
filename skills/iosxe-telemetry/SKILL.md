---
name: iosxe-telemetry
description: >
  Analyze Catalyst 9000 IOS-XE model-driven telemetry stored in the ClawLab TIG
  stack (Telegraf → InfluxDB → Grafana). Use when the user asks about switch CPU,
  memory, interface counters, or MDT metrics — not syslog (those are in Splunk).
---

# IOS-XE telemetry (TIG)

Operational **streaming metrics** from Catalyst 9000 live in the lab **TIG stack**:

| Component | Role |
|-----------|------|
| **Telegraf** | Receives MDT gRPC dial-out on port **57000** |
| **InfluxDB** | Bucket `iosxe_telemetry` at `127.0.0.1:8086` |
| **Grafana** | Dashboards at `http://127.0.0.1:3000/` |

**Splunk is not the MDT store** — syslog alerts already go to Splunk separately.
Do not suggest indexing raw MDT into Splunk.

## When to use

- CPU / memory trends on switches
- Interface utilization, errors, drops from MDT YANG paths
- “Any telemetry in the last hour?” before Grafana MCP is wired

## When not to use

- **Syslog / EEM / auth failures** → Splunk (existing pipeline)
- **Config changes / IOS CLI** → ssh-ops MCP
- **ThousandEyes path/app performance** → ThousandEyes MCP

## Manual checks (lab host)

```bash
bash tests/iosxe-telemetry-ping.sh
bash iosxe-telemetry/podctl.sh --status
source ~/.clawlab/telemetry/env
influx query 'from(bucket:"iosxe_telemetry") |> range(start: -1h) |> limit(n:10)' \
  --host http://127.0.0.1:8086 --org clawlab --token "$INFLUX_TOKEN"
```

## Switch subscriptions

MDT must be configured on each switch (dial-out to Telegraf host IP, port 57000).
See `iosxe-telemetry/README.md` for XPath examples. Future: gated via ssh-ops
`telemetry ietf subscription` policy group.

## Coming soon

- **Grafana MCP** in OpenClaw for Flux queries from chat
- ios-xe-policy group for subscription provisioning
