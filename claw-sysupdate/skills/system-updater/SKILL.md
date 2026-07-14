---
name: system-updater
description: >
  Keep the Linux host patched. Use when the user asks to update the system,
  apply patches, check for available updates, or check whether a reboot is
  pending. Applies ALL apt updates via a governed systemd service and reports
  the result. Never reboots on its own — it flags when a reboot is required and
  lets the user decide.
---

# System Updater

This skill drives the `claw-sysupdate` service on the host. It triggers the
service, waits, then reads and reports the JSON summary — surfacing a required
reboot without ever performing it.

## Policy (do not deviate)

- Apply all updates (full-upgrade), not just security.
- Never reboot. If `reboot_required` is true, tell the user which packages need
  it and that they must reboot manually (`sudo systemctl reboot`).
- Only run the two approved commands below. DefenseClaw governs this skill.

## How to run an update

1. Trigger (blocks until finished):
   sudo systemctl start claw-sysupdate.service
2. Read the result:
   cat /var/lib/claw-sysupdate/last-run.json
3. Report `upgraded_count`, `status`, and `reboot_required` (+ `reboot_pkgs`).

## How to just check (no changes)

apt-get -s dist-upgrade | awk '/^Inst /{print $2}'

## Notes

- The service also runs automatically on a daily timer.
- Full logs per run live in /var/log/claw-sysupdate/.
