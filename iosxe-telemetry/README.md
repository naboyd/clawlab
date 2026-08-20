# IOS-XE telemetry — Telegraf + InfluxDB + Grafana (TIG)

Model-driven telemetry (MDT) from Catalyst 9000 switches lands in **InfluxDB** via
**Telegraf**. **Grafana** is for validation dashboards. **Splunk is out of scope**
for this path — IOS syslog alerts already go to Splunk separately.

## Architecture

```text
Catalyst 9000 ──gRPC MDT :57000──► Telegraf (cisco_telemetry_mdt)
                                        │
                                        ▼
                                   InfluxDB 2.x  (bucket: iosxe_telemetry)
                                        │
                                        └── Grafana :3000 (LAN + portal /grafana/)
```

| Service | Default bind | Purpose |
|---------|--------------|---------|
| Telegraf | `LAN_IP:57000` (from portal config) | MDT dial-out receiver |
| InfluxDB | `127.0.0.1:8086` | Time-series store |
| Grafana | `LAN_IP:3000` + portal `/grafana/` | Dashboards (hub Telemetry tab) |

Data and secrets: `~/.clawlab/telemetry/` (not in git).

## Install (lab host)

```bash
cd ~/clawlab
bash admin-access/install-iosxe-telemetry-stack.sh
bash iosxe-telemetry/podctl.sh --status
bash tests/iosxe-telemetry-ping.sh
```

## Switch subscription (example)

Point the switch at the Telegraf host IP (icecream LAN address) on port **57000**.
Use gRPC-TLS in production; lab may use plaintext gRPC only if your IOS-XE build
allows it (prefer TLS + trustpoint).

```text
telemetry ietf subscription 1
 encoding encode-kvgpb
 filter xpath /process-cpu-ios-xe-oper:cpu-usage/cpu-utilization
 stream yang-push
 update-policy periodic 1000
 receiver ip address <telegraf-host-ip> 57000 protocol grpc-tls profile <trustpoint>
```

See Cisco [IOS-XE MDT documentation](https://www.cisco.com/c/en/us/td/docs/switches/lan/c9000/prog/mdt/model-driven-telemetry.html).

## Operations

```bash
bash iosxe-telemetry/podctl.sh              # ensure up
bash iosxe-telemetry/podctl.sh --recreate   # restart all containers
bash iosxe-telemetry/podctl.sh --stop
bash iosxe-telemetry/podctl.sh --logs telegraf
```

Grafana UI:

- **Portal hub:** `Telemetry` tab → `https://<host>:8443/grafana/` (claw-auth)
- **MCP Admin:** nav link **Telemetry ↗**
- Direct on LAN: `http://<LAN_IP>:3000/` (Grafana login; admin password in env)

After portal or LAN IP changes:

```bash
bash admin-access/sync-iosxe-telemetry-grafana-portal.sh
sudo nginx -t && sudo systemctl reload nginx   # if nginx /grafana/ location missing
```

Influx CLI (from host):

```bash
source ~/.clawlab/telemetry/env
influx query 'from(bucket:"iosxe_telemetry") |> range(start: -1h) |> limit(n:5)' \
  --host http://127.0.0.1:8086 --org clawlab --token "$INFLUX_TOKEN"
```

## Next phases (not in this package yet)

- OpenClaw **Grafana MCP** (`grafana/mcp-grafana`) for agent queries
- ios-xe-policy group for gated `telemetry ietf subscription` via ssh-ops
- Optional Splunk HEC for derived alerts only (syslog already covers many alerts)
