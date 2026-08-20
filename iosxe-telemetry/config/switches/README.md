# Switch MDT configs (IOS-XE → ClawLab Telegraf)

| File | Switch | Purpose |
|------|--------|---------|
| `9300-24-Office-mdt-test.conf` | 9300-24-Office | CPU, memory, interface MDT test (601–603) |
| `9300-24-Office-mdt-test-rollback.conf` | same | Remove subscriptions 601–603 |
| `9300-24-Office-mdt-phase2.conf` | same | Platform, env, PoE, LLDP, STP (604–608); tune 603 → 30s |
| `9300-24-Office-mdt-phase2-fix.conf` | same | Correct XPaths for invalid 606–608 |
| `9300-24-Office-mdt-phase2-rollback.conf` | same | Remove subscriptions 604–608 |

## Generate (custom collector IP / VRF)

```bash
bash iosxe-telemetry/scripts/gen-mdt-test-config.sh --host 9300-24-Office
bash iosxe-telemetry/scripts/gen-mdt-phase2-config.sh --host 9300-24-Office
```

Environment overrides:

| Variable | Default |
|----------|---------|
| `MDT_COLLECTOR_IP` | From `~/.clawlab/telemetry/env` or portal `LAN_IP` |
| `MDT_COLLECTOR_PORT` | `57000` |
| `MDT_PROTOCOL` | `grpc-tcp` (lab; Telegraf without TLS) |
| `MDT_PERIOD_MS` | `5000` |
| `MDT_SOURCE_VRF` | (none) |
| `MDT_SOURCE_ADDRESS` | (none) |

## Apply on 9300-24-Office

**Option A — paste config**

1. SSH to the switch (or MCP Admin → run read-only `show clock`, `show ip route`).
2. `configure terminal`
3. Paste contents of `9300-24-Office-mdt-test.conf` (skip `configure terminal` / `end` if already in config mode).
4. `end` → `write memory`

**Option B — ssh-ops host name** (if `9300-24-Office` is in MCP inventory):

```bash
bash iosxe-telemetry/scripts/gen-mdt-test-config.sh --host 9300-24-Office --apply
```

Use `--dry-run` to print the target without pushing.

## Verify

**On switch:**

```text
show telemetry ietf subscription all
show telemetry ietf subscription 601
```

State should show active/receiving; if `Channel state: UNKNOWN` or retries, check routing and that Telegraf is listening (`bash tests/iosxe-telemetry-ping.sh` on icecream).

**On icecream:**

```bash
podman logs --tail 50 iosxe-telegraf
bash tests/iosxe-telemetry-ping.sh
```

Then Grafana → Telemetry tab → Explore → bucket `iosxe_telemetry`.

## Subscriptions

| ID | XPath | Data |
|----|-------|------|
| 601 | `.../cpu-utilization/five-seconds` | CPU |
| 602 | `.../memory-statistic` | Memory |
| 603 | `.../interfaces/interface` | Interface counters (phase 2: 30s) |
| 604 | `.../components/component` | Platform hardware |
| 605 | `.../environment-sensor` | Temps / power sensors |
| 606 | `.../poe-oper-data/poe-port-detail` | PoE per port |
| 607 | `.../lldp-entries/lldp-entry` | LLDP neighbors |
| 608 | `.../stp-details/stp-detail` | STP per-instance |

## Rollback

Paste `9300-24-Office-mdt-test-rollback.conf` or:

```text
configure terminal
 no telemetry ietf subscription 601
 no telemetry ietf subscription 602
 no telemetry ietf subscription 603
end
```
