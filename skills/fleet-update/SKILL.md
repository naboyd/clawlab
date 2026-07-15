---
name: fleet-update
description: >
  Patch the Linux fleet. Use when the user asks to update the fleet, patch the
  servers, run fleet updates, or check which hosts need updates/reboots. Drives
  the per-host claw-sysupdate service through the ssh-ops MCP and reports a
  combined summary. Never reboots — it flags reboots for the user.
---

# Fleet Update

Use the **ssh-ops** MCP tools. A host is in scope when its platform is linux AND
`list_hosts` reports `auto_update: true` (checkbox/tag) or `auto_update` appears
in `tags`.

## Steps
1. `list_hosts` → select the linux hosts where `auto_update` is true or `tags` contains `auto_update`.
2. For each selected host, in sequence:
   - `run_write_command(host, "sudo systemctl start claw-sysupdate.service")`
   - `run_command(host, "cat /var/lib/claw-sysupdate/last-run.json")`
3. Summarize per host: `upgraded_count`, `status`, and `reboot_required`
   (+ `reboot_pkgs`). If any host needs a reboot, call it out and tell the user
   it requires a **manual** reboot — never reboot anything yourself.

Only use those two commands per host. DefenseClaw governs this skill.
