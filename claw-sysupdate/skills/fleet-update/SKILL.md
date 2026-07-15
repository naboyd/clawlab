---
name: fleet-update
description: >
  Keep multiple Linux hosts patched. Use when the user asks to update the fleet,
  update all hosts, patch the servers, or check which hosts have updates or need
  a reboot. Enumerates hosts flagged for auto-update in the SSH-ops MCP host
  inventory, triggers the per-host updater on each, and reports a combined
  summary. Never reboots any host — it flags reboots for the user to decide.
---

# Fleet Update

Patches every Linux host flagged for auto-update in the SSH-ops MCP host
inventory (the host file is the single source of truth). Per-host patching is
done by each host's own claw-sysupdate service; this skill orchestrates/reports.

## Which hosts are in scope

Both must be true: platform/kind is linux, AND `auto_update` is true from
`list_hosts` (or the `auto_update` tag is present).

## Flag convention

Preferred: **Auto-update** checkbox in MCP Admin (sets `auto_update: true` and
adds the `auto_update` tag). Alternatively include `auto_update` in **Tags**.
Other flows can filter on any tag via `list_hosts.tags`.

## Procedure

1. list_hosts -> select linux hosts with the flag.
2. For each, in sequence:
   a. run_write_command(host, "sudo systemctl start claw-sysupdate.service")
   b. run_command(host, "cat /var/lib/claw-sysupdate/last-run.json")
3. Aggregate: per-host upgraded_count, status, reboot_required (+ reboot_pkgs).
4. If any host reboot_required=true, call it out and say it needs a MANUAL
   reboot. Never reboot anything.

## Requirements per host (one-time)

allow_write:true + the flag in the MCP entry; scoped passwordless sudo
(systemctl, apt); the claw-sysupdate updater+timer installed. See FLEET.md.

## Guardrails

Only run the two commands above. DefenseClaw governs this skill.
