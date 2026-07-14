# claw-portals — unified admin portal installer

One installer for all clawlab browser admin surfaces:

| Portal | Backend | Default HTTPS port |
|--------|---------|-------------------|
| ssh-ops admin GUI | `127.0.0.1:8765` | 8443 |
| OpenClaw Control UI | `127.0.0.1:18789` | 8444 |
| DefenseClaw policy editor | `127.0.0.1:8770` | 8445 |

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
3. **HTTP only** — lab use; ports 8083/8084/8085

**Auth mode**
1. **claw-auth** (recommended) — lightweight SQLite user DB, shared across portals
2. **pam** — legacy Linux system accounts via nginx `auth_pam`

### Non-interactive

```bash
./install-portals.sh --non-interactive --tls=https-le --auth=claw-auth
```

Requires `~/mcp/acme/godaddy.env` for LE mode.

## What it installs

- `claw-auth.service` — centralized auth on `127.0.0.1:8780` (claw-auth mode)
- `defenseclaw-webgui.service` — policy editor on `127.0.0.1:8770`
- nginx site configs under `/etc/nginx/sites-enabled/clawlab-*.conf`
- `~/.claw-portals/config.env` — saved choices and portal URLs

**Prerequisites** (not installed by this script):
- ssh-ops GUI quadlet (`8765`)
- OpenClaw gateway (`18789`)
- GoDaddy API creds in `~/mcp/acme/godaddy.env` for LE issuance

## After install

1. Create additional users: `python3 ../claw-auth/manage.py create-user NAME`
2. For OpenClaw single sign-on at the gateway layer, merge
   `admin-access/openclaw.trusted-proxy.json5` into `~/.openclaw/openclaw.json`
   and set `allowedOrigins` to your Control UI URL (port 8444 by default).
3. Run the `defenseclaw-canary` skill to verify policy enforcement.

## Config file

`~/.claw-portals/config.env` sets:

- `CLAW_AUTH_REQUIRED=1` — Flask apps enforce proxy auth
- `CLAW_PORTAL_*_URL` — portal hub links in claw-auth
- Port and TLS settings for re-runs

Re-run `./install-portals.sh` to change TLS or auth mode.

## Port map

| Mode | ssh-ops | OpenClaw | DefenseClaw |
|------|---------|----------|-------------|
| HTTPS | 8443 | 8444 | 8445 |
| HTTP | 8083 | 8084 | 8085 |

Auth service (internal): `127.0.0.1:8780`
