---
name: ios-config-drift
description: >
  Archive Cisco IOS running-configs and detect out-of-band configuration drift.
  Use when the user asks to archive switch configs, check config drift, compare
  running-config to baseline, or investigate changes not in the MCP change log.
---

# IOS Config Drift

Read-only diagnostics plus an optional on-demand drift check. **Never** push
config with `run_write_command` or unapproved CLI — gated changes use
`propose_change` → human approve → `apply_change`.

## Scope

Network hosts (`platform: cisco_ios` / ios-xe) in `list_hosts`. Hosts tagged
`no_config_archive` are skipped; tag `config_archive` forces inclusion.

Archives live on the ssh-ops data host (icecream):

`~/.clawlab/ssh-ops/data/ios-config-archive/{host}/`

- `baseline.txt` — last accepted reference config
- `snapshots/` — timestamped daily pulls
- `diffs/` — unified diff + `-new.txt` when drift is unexplained

## On-demand (MCP tools)

Prefer these ssh-ops MCP tools when available:

1. `check_ios_config_drift()` — all in-scope hosts; returns per-host status
2. `check_ios_config_drift(host="SW1")` — single switch
3. `get_ios_config_archive_status(host="SW1")` — paths and last run summary

Status values:

| status | meaning |
|--------|---------|
| `baseline_initialized` | first snapshot stored |
| `unchanged` | matches baseline |
| `changed_in_band` | diff explained by applied MCP change |
| `out_of_band` | diff **not** in change log → Webex alert sent |

## Manual trigger on icecream

If MCP tools are unavailable, run on the lab host (not via agent SSH):

```bash
python3 ~/clawlab/ssh-ops-mcp/scripts/ios-config-drift-check.py
```

## Daily schedule

Installed via `admin-access/install-ios-config-archive.sh` — systemd user timer
~04:00 local with 30m jitter.

## Webex alerts

Out-of-band drift posts to DefenseClaw Webex webhooks whose `events` include
`drift`, `change`, or `config_drift`. Disable with `SSH_OPS_NOTIFY_DRIFT=0`.

## Related workflow

Expected changes should appear in MCP Admin → Changes (`list_changes` with
status `applied`). If drift fires after a legitimate console change, document
the incident and rebaseline is automatic after alert.
