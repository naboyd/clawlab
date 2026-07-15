# claw-portals — unified admin portal installer

One URL, one port, tabbed hub for all clawlab browser admin surfaces.

| Tab | Path | Backend |
|-----|------|---------|
| OpenClaw Control UI | `/openclaw/` | `127.0.0.1:18789` |
| MCP Admin (ssh-ops) | `/ssh-ops/` | `127.0.0.1:8765` |
| DefenseClaw policies | `/defenseclaw/` | `127.0.0.1:8770` |

**Default portal URL:** `https://<host>:8443/` (HTTP lab mode: `:8083`)

Sign in once at the hub; tabs load each manager in an iframe on the same origin.

## Quick start

```bash
cd claw-portals
chmod +x install-portals.sh
./install-portals.sh
```

### Interactive choices

**TLS mode**
1. **HTTPS + Let's Encrypt** (recommended) — uses lego + GoDaddy DNS-01 (`acme/issue-cert.sh`)
2. **HTTPS + existing cert** — supply paths to `.crt` / `.key`
3. **HTTP only** — lab use; port 8083

**Auth mode**
1. **claw-auth** (recommended) — lightweight SQLite user DB, shared across all paths
2. **pam** — legacy Linux system accounts via nginx `auth_pam`

### Non-interactive

```bash
./install-portals.sh --non-interactive --tls=https-le --auth=claw-auth
```

Requires `~/mcp/acme/godaddy.env` for LE mode.

## What it installs

- `claw-auth.service` — login, verify, and tabbed hub on `127.0.0.1:8780` (claw-auth mode)
- `defenseclaw-webgui.service` — policy editor on `127.0.0.1:8770` (`PORTAL_MOUNT_PATH=/defenseclaw`)
- nginx **`clawlab-portal.conf`** — single server block with path-based routing
- `~/.claw-portals/config.env` — saved choices and portal URLs

**Prerequisites** (not installed by this script):
- ssh-ops GUI quadlet (`8765`)
- OpenClaw gateway (`18789`)
- GoDaddy API creds in `~/mcp/acme/godaddy.env` for LE issuance
- `python3-venv` (installer runs `sudo apt install python3-venv python3-full` if needed)

Python packages install into **`~/.clawlab/venv`** (avoids PEP 668 system pip errors).

## After install

1. Bookmark **`CLAW_PORTAL_HUB_URL`** from `~/.claw-portals/config.env`
2. Create additional users: `python3 ../claw-auth/manage.py create-user NAME`
3. For OpenClaw Control UI behind the proxy, merge
   `admin-access/openclaw.trusted-proxy.json5` into `~/.openclaw/openclaw.json`
   and set `allowedOrigins` to the portal origin (e.g. `https://icecream:8443` — no path).
4. Rebuild ssh-ops after pull: `podman build -t ssh-ops:latest ~/clawlab/ssh-ops-mcp && systemctl --user restart ssh-ops-gui`
5. Run the `defenseclaw-canary` skill to verify policy enforcement.

## Config file

`~/.claw-portals/config.env` sets:

- `CLAW_PORTAL_HUB_URL` — bookmark this
- `CLAW_PORTAL_*_PATH` — iframe paths for the hub tabs
- `CLAW_AUTH_REQUIRED=1` — Flask apps enforce proxy auth
- `PORT_PORTAL` — single nginx listen port

Re-run `./install-portals.sh` to change TLS or auth mode.

## Port map

| Mode | Portal hub |
|------|------------|
| HTTPS | 8443 |
| HTTP | 8083 |

Auth service (internal): `127.0.0.1:8780`

Legacy per-port configs (`8443`/`8444`/`8445`) are removed when the unified config is deployed.

## OpenClaw subpath note

The OpenClaw Control UI is proxied at `/openclaw/`. The gateway must have
`gateway.controlUi.basePath` set to `/openclaw` (no trailing slash). nginx
forwards the full `/openclaw/...` path to the gateway (do not strip the prefix).

```bash
python3 claw-portals/apply-openclaw-portal.py
systemctl --user restart openclaw-gateway
```

If assets or WebSockets still fail, open `/openclaw/` in a new window and confirm
`controlUi.allowedOrigins` includes your portal origin (e.g. `https://icecream:8443`).
