# clawlab

Self-hosted AI-ops lab: a governed OpenClaw agent on the host **icecream**, with a
Cisco DefenseClaw governance layer, a hardened **ssh-ops** MCP, Let's Encrypt TLS,
centralized **claw-auth** admin login (SQLite, with legacy PAM optional), a unified
tabbed portal hub, and alerting into Cisco Webex.

> **Secrets never live here.** All tokens, API keys, the Fernet `master.key`, LE
> private keys, and `.env` files are git-ignored. Config *templates* (with values
> redacted to `<PLACEHOLDER>`) live in `config-templates/`. Copy them to the real
> locations and fill in secrets locally.

## Project status (Jul 2026)

Work completed on this repo for the **icecream** lab host
(`icecream.naboydciscolab.com`, LAN `192.168.128.93`):

### Governance & agent stack

- **OpenClaw** gateway on loopback `:18789` with DefenseClaw plugin enforcing guardrails,
  rule packs, admission actions, and audit logging.
- **DefenseClaw policy editor** (`defenseclaw-webgui/`) — Flask UI for guardrail settings,
  rule-pack YAML, actions, webhooks, firewall rules, and audit views.
- **ssh-ops MCP** (`ssh-ops-mcp/`) — hardened remote command MCP with Fernet-encrypted
  credentials, audit log, bearer-token MCP endpoint, and Podman-hosted admin GUI.

### Centralized auth (`claw-auth/`)

Replaced per-portal PAM as the recommended path:

- SQLite user database at `~/.claw-auth/users.db`
- Login, logout, nginx `auth_request` verify, and user admin UI
- Session cookies shared across all portal paths on one origin
- `manage.py` CLI for user CRUD; `doctor.sh` for health checks
- Logs: `journalctl --user -u claw-auth` and `~/.claw-auth/auth.log`

### Unified portal hub (`claw-portals/`)

Single bookmark URL instead of three ports:

| Tab | Path | Backend |
|-----|------|---------|
| OpenClaw Control UI | `/openclaw/` | `127.0.0.1:18789` |
| MCP Admin (ssh-ops) | `/ssh-ops/` | `127.0.0.1:8765` |
| DefenseClaw policies | `/defenseclaw/` | `127.0.0.1:8770` |

- **Default URL:** `https://<host>:8443/` (HTTP lab: `:8083`)
- Tabbed hub in claw-auth serves iframes; one login covers all managers
- `install-portals.sh` — interactive or `--non-interactive` installer for TLS
  (HTTP / HTTPS+Let's Encrypt / existing cert), auth mode, nginx, and systemd units
- Path-based nginx config (`clawlab-portal.conf`) replaces legacy per-port sites
- `portal_mount.py` — Flask apps honor `PORTAL_MOUNT_PATH` for subpath routing
- Python deps in `~/.clawlab/venv` (PEP 668 safe on modern Debian/Ubuntu)

### Deployment fixes (icecream)

- Executable install scripts; `--deploy-nginx-only` for sudo nginx re-runs
- Login form posts to correct `/_claw_auth/login` path (fixed redirect loop)
- ssh-ops container requires `X-Auth-User` from nginx; direct `:8765` returns 403
- Podman image rebuild wired into installer; quadlet sets `PORTAL_MOUNT_PATH=/ssh-ops`

### Still manual / prerequisites

- OpenClaw gateway must be running (`openclaw-gateway.service`)
- Update `~/.openclaw/openclaw.json` `controlUi.allowedOrigins` to portal port **8443**
- GoDaddy DNS creds in `~/mcp/acme/godaddy.env` for Let's Encrypt issuance
- MCP bearer token for ssh-ops unchanged on `:8766`

### Quick redeploy after `git pull`

```bash
cd ~/clawlab
bash claw-portals/install-portals.sh --non-interactive --tls=https-le --auth=claw-auth
systemctl --user restart claw-auth defenseclaw-webgui
podman build -t ssh-ops:latest ~/clawlab/ssh-ops-mcp
systemctl --user restart ssh-ops-gui
bash claw-auth/doctor.sh
```

## Layout

| Path | What it is |
|------|-----------|
| `ssh-ops-mcp/` | The ssh-ops MCP server (FastMCP): `server.py`, `secrets_store.py` (Fernet), `webgui.py` (admin GUI + token rotation), `Dockerfile`, `entrypoint.sh`, `hosts.example.yaml`. |
| `claw-auth/` | Centralized SQLite auth for all admin portals (replaces PAM). |
| `claw-portals/` | Unified installer + tabbed portal hub: HTTP/HTTPS+LE, claw-auth or PAM, single-port nginx (`:8443`). |
| `defenseclaw-webgui/` | Policy editor web UI (Flask): guardrail settings, rule-pack YAML, actions, webhooks, firewall. Loopback :8770; LAN via unified portal at `/defenseclaw/`. |
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
4. Install portals: `claw-portals/install-portals.sh` (TLS + claw-auth + nginx for all admin UIs).
   Or individually: `ssh-ops-mcp/` (quadlets), `defenseclaw-webgui/install-webgui.sh`,
   `defenseclaw-webex-bridge/install-webex-bridge.sh`, `claw-sysupdate/install-claw-sysupdate.sh` (sudo).
5. Issue the LE cert with lego (GoDaddy DNS-01) if not using `install-portals.sh --tls=https-le`, then `systemctl --user enable --now` the timers.

## Notes

- Admin GUIs bind loopback only; LAN access via nginx + **claw-auth** (recommended) or legacy PAM.
  One portal URL: `https://<host>:8443/` with tabs for OpenClaw, MCP Admin, and DefenseClaw.
- DefenseClaw enforces via subprocess shims + tool-call inspection (deterministic `strict` rule pack);
  the webex bridge tails `audit.db` and posts violations.
