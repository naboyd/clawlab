# clawlab

Self-hosted AI-ops lab: a governed OpenClaw agent on the host **icecream**, with a
Cisco DefenseClaw governance layer, a hardened **ssh-ops** MCP, Let's Encrypt TLS,
PAM-authenticated admin UIs, and alerting into Cisco Webex.

> **Secrets never live here.** All tokens, API keys, the Fernet `master.key`, LE
> private keys, and `.env` files are git-ignored. Config *templates* (with values
> redacted to `<PLACEHOLDER>`) live in `config-templates/`. Copy them to the real
> locations and fill in secrets locally.

## Layout

| Path | What it is |
|------|-----------|
| `ssh-ops-mcp/` | The ssh-ops MCP server (FastMCP): `server.py`, `secrets_store.py` (Fernet), `webgui.py` (admin GUI + token rotation), `Dockerfile`, `entrypoint.sh`, `hosts.example.yaml`. |
| `defenseclaw-webex-bridge/` | Audit→Webex alert bridge (`dc-webex-bridge.py`) + systemd unit + installer. Fires Webex on HIGH/CRITICAL DefenseClaw violations (closes the 0.8.4 dispatch gap). |
| `quadlets/` | Rootless podman Quadlet units for the ssh-ops MCP + admin GUI containers. |
| `systemd-user/` | User services/timers: gateway, lego cert renewal, DefenseClaw ext self-heal, webex bridge. |
| `nginx/` + `pam/` | Reverse proxies (LE TLS + PAM/Linux-user auth) for the admin GUI, Control UI, MCP. |
| `admin-access/` | Installer + configs for LAN admin access (nginx + auth_pam + trusted-proxy). |
| `model-tiering/` | OpenClaw model config (local ollama primary + Claude fallback). |
| `claw-sysupdate/` | Auto-updater service/timer + fleet-update / system-updater skills. |
| `skills/` | OpenClaw skills: `fleet-update`, `system-updater`, `defenseclaw-canary`. |
| `acme/` | GoDaddy DNS-01 env template for lego. |
| `config-templates/` | Sanitized `openclaw.sample.json`, `defenseclaw.sample.yaml`, and `*.env.example`. |

## Bring-up (new device / rebuild)

1. Copy `config-templates/*.env.example` → the real `.env` locations and fill in secrets.
2. Copy `config-templates/openclaw.sample.json` → `~/.openclaw/openclaw.json`, replace `<...>` placeholders.
   - Note: each model provider needs a `models: [...]` array — the `anthropic` provider entry
     must include one or the gateway crashes in failover (`reading 'find'`). See the sample.
3. Copy `config-templates/defenseclaw.sample.yaml` → `~/.defenseclaw/config.yaml`, set `room_id`.
4. Install units: `ssh-ops-mcp/` (quadlets), `defenseclaw-webex-bridge/install-webex-bridge.sh`,
   `admin-access/setup-admin-access.sh` (sudo), `claw-sysupdate/install-claw-sysupdate.sh` (sudo).
5. Issue the LE cert with lego (GoDaddy DNS-01), then `systemctl --user enable --now` the timers.

## Notes

- ssh-ops MCP: streamable-http on :8766, bearer-token auth, TLS; admin GUI on :8765 behind nginx PAM.
- DefenseClaw enforces via subprocess shims + tool-call inspection (deterministic `strict` rule pack);
  the webex bridge tails `audit.db` and posts violations.
