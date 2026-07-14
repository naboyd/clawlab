# DefenseClaw audit → Webex bridge

Fires a Webex alert for every HIGH/CRITICAL security violation DefenseClaw
records, closing a gap in DefenseClaw 0.8.4 where the enforcing lanes don't
reach the built-in webhook dispatcher.

## Why it's needed

For the OpenClaw connector in 0.8.4:

- The lanes that reliably **catch** attacks — the subprocess shims
  (`curl`/`nc`/`wget`/`ssh`/`npm`/`pip`) and tool-call inspection — log
  `would_block=false`. They enforce at the shell level (the shim exits non-zero
  and the command never runs) but are treated as *advisory* by the gateway, so
  they never fire the runtime webhook dispatcher.
- The only lane that natively dispatches Webex (`guardrail` events) is the
  **prompt-lane LLM judge**, which on the local `Foundation-Sec-8B-Q8` model is
  unreliable (returns prose instead of a verdict → parse error) and runs as an
  async sweep, too late to block.

So qualifying events land in the audit DB but no Webex message is sent. This
bridge tails that audit DB — which the **deterministic pattern engine** (the
`strict` rule pack) writes to reliably — and dispatches the alerts itself.

## What it does

- Opens `~/.defenseclaw/audit.db` **read-only** and polls `audit_events` for new
  rows (tracks a rowid cursor; no historical replay on first start).
- Selects genuine violations: `inspect-tool-block`, `*-block`, `guardrail*`,
  meaningful `llm-judge-response` (injection/exfil/pii), non-operator `drift`,
  and CRITICAL `scan`s — at/above the webhook's `min_severity`.
- Posts a formatted Webex markdown card to the **same** endpoint/room/token
  already configured under `webhooks:` in `config.yaml` (+ token from `.env`).
  Rotating the Webex token or room in DefenseClaw needs no change here.
- De-dups bursts (same action+target+severity within 60s) and remembers the
  last 500 event IDs across restarts.

It never writes to DefenseClaw state (only its own `webex-bridge.state`), so it
cannot interfere with the gateway.

## Install

```bash
./install-webex-bridge.sh
```

Runs as a rootless **systemd user** service (`dc-webex-bridge.service`) — no
sudo. Enables linger so it survives logout.

## Operate

```bash
journalctl --user -u dc-webex-bridge -f          # live logs
python3 ~/.defenseclaw/webex-bridge/dc-webex-bridge.py --test   # synthetic alert
systemctl --user restart dc-webex-bridge
```

## Tuning

- Poll interval: `--poll SECONDS` (default 5) or `DC_BRIDGE_POLL`.
- De-dup window: `--dedup-window SECONDS` (default 60) or `DC_BRIDGE_DEDUP`.
- Alert selection lives in `categorize()` / `is_violation()` in
  `dc-webex-bridge.py` — edit to widen/narrow what pages you.

## Note

This is a stopgap for the 0.8.4 dispatch gap. If a later DefenseClaw release
wires tool-call enforcement + dispatch (the "Round-2" lanes), you can retire the
bridge and rely on the native dispatcher.
