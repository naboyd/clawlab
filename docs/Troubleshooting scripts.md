# Troubleshooting scripts

Shell helpers for **pre-beta testers** — install checks, portal/OpenClaw diagnostics,
policy refresh, and stack control. Run from the repo root unless noted.

Maintainer-only scripts (legacy lab redeploy, training benches, DHCP sidecar deploy,
trusted-proxy helpers, duplicate PAM/nginx snippets) live in **`_archive/`**
(gitignored except `_archive/README.md`). Restore with
`bash admin-access/populate-maintainer-archive.sh` or copy paths from `_archive/`.

---

## Install & stack health

### `install/preinstall-check.sh`

Read-only prerequisite checklist before `install-clawstack.sh`. Optional conservative fixes.

| Flag / env | Description |
|------------|-------------|
| *(none)* | Report only |
| `--fix` | Apply safe apt/brew/pnpm fixes where supported |
| `--mode=local` | Default — desktop/agent checks |
| `--mode=local-full` | Include portal `:8083`, nginx, claw-auth checks |
| `--mode=server` | Include Linux server/TLS/nginx checks |
| `-h`, `--help` | Show usage |

```bash
bash install/preinstall-check.sh
bash install/preinstall-check.sh --fix
bash install/preinstall-check.sh --mode=local-full
```

### `install/verify-local-full.sh`

Post-install smoke test for **local-full** (ports, nginx, gateway, device list).

| Flag / env | Description |
|------------|-------------|
| *(none)* | Run all checks |
| `LOCAL_FULL_PORT` | Portal port (default `8083`) |

```bash
bash install/verify-local-full.sh
```

### `install/local-full-ctl.sh`

Start/stop the loopback stack (Mac/desktop, no systemd).

| Subcommand | Description |
|------------|-------------|
| `start` | Start claw-auth, backends, nginx, gateway |
| `stop` | Stop managed services |
| `status` | Show listening ports and PIDs |
| `restart` | Stop then start |

```bash
bash install/local-full-ctl.sh status
bash install/local-full-ctl.sh restart
```

---

## Portal & OpenClaw

### `claw-auth/doctor.sh`

claw-auth health plus optional **lab portal** verification (`:8443` / `install-portals.sh`).
Each run is appended to `~/.clawlab/run/claw-auth-doctor.log`.

| Flag / env | Description |
|------------|-------------|
| *(none)* | claw-auth checks; auto-runs lab portal verify when `~/.claw-portals/config.env` is HTTPS / `:8443` |
| `--verify-lab-portal` | Force lab portal checks (`install/verify-lab-portal.sh`) |
| `--no-log` | Print only; do not append to doctor log |
| `CLAWLAB_DOCTOR_LOG` | Doctor log path (default `~/.clawlab/run/claw-auth-doctor.log`) |
| `CLAWLAB_VENV` | Python venv path (default `~/.clawlab/venv`) |
| `CLAW_AUTH_HOME` | Auth data dir (default `~/.claw-auth`) |

```bash
bash claw-auth/doctor.sh
bash claw-auth/doctor.sh --verify-lab-portal
```

### `install/verify-lab-portal.sh`

Standalone lab portal post-install checks (systemd, podman, nginx, portal HTTP, MCP ports).
Used by `claw-auth/doctor.sh --verify-lab-portal`.

```bash
bash install/verify-lab-portal.sh
```

### Install log

`install-clawstack.sh` and `install-portals.sh` append output to **`~/.clawlab/run/install.log`**
(session headers per run). Override with `CLAWLAB_INSTALL_LOG`.

### `admin-access/diagnose-openclaw-portal.sh`

Print OpenClaw gateway/portal config and curl probes for `/openclaw/`.

| Env | Description |
|-----|-------------|
| `OPENCLAW_CONFIG` | Path to `openclaw.json` |
| `PORT_PORTAL` | Portal port (default `8443`; use `8083` for local-full) |
| `DOMAIN` | FQDN used in allowedOrigins checks |
| `LAN_IP` | LAN IP used in checks |

```bash
PORT_PORTAL=8083 bash admin-access/diagnose-openclaw-portal.sh
```

### `admin-access/test-openclaw-wss.sh`

HTTP + WebSocket upgrade checks through nginx and loopback gateway.

| Env | Description |
|-----|-------------|
| `LAN_IP` | Host for HTTPS probe (default lab LAN IP) |
| `PORT_PORTAL` | Portal port (default `8443`) |

```bash
PORT_PORTAL=8083 LAN_IP=127.0.0.1 bash admin-access/test-openclaw-wss.sh
```

### `admin-access/print-gateway-url.sh`

Print Control UI URLs with `#token=` (does not echo the token value).

| Env | Description |
|-----|-------------|
| `DOMAIN` | FQDN link variant |
| `LAN_IP` | LAN IP link variant |
| `PORT_PORTAL` | Portal port |
| `OPENCLAW_HOME` | OpenClaw config dir |

```bash
bash admin-access/print-gateway-url.sh
```

### `admin-access/configure-openclaw-mcp-identity.sh`

Enable clawlab MCP identity plugin and point ssh-ops MCP at the identity proxy.

| Env | Description |
|-----|-------------|
| `OPENCLAW_HOME` | OpenClaw dir (default `~/.openclaw`) |
| `SSH_OPS_MCP_PROXY_URL` | Proxy URL (default `http://127.0.0.1:8767/mcp`) |
| `SSH_OPS_MCP_PROXY_BIND` | Listen address (default `127.0.0.1`; use lab LAN IP for Claude Desktop without SSH tunnel) |
| `SSH_OPS_MCP_PROXY_TLS_CERT` / `SSH_OPS_MCP_PROXY_TLS_KEY` | TLS for the proxy (auto from lego + `DOMAIN` in `~/.claw-portals/config.env` when present) |
| `CLAW_PYTHON` | Python for JSON patch |

```bash
bash admin-access/configure-openclaw-mcp-identity.sh
```

---

## DefenseClaw & policies

### `admin-access/install-clawlab-guardrail-rules.sh`

Merge clawlab guardrail rules and IOS-XE policy into the active DefenseClaw pack; reload gateway.

| Env | Description |
|-----|-------------|
| `RULE_PACK_DIR` | Override rule pack path |
| `DEFENSECLAW_HOME` | DefenseClaw home (default `~/.defenseclaw`) |
| `CLAW_PYTHON` | Python interpreter |

```bash
bash admin-access/install-clawlab-guardrail-rules.sh
```

### `admin-access/refresh-clawlab-policies.sh`

Sync policy templates from the repo after `git pull`; optional ssh-ops rebuild.

| Flag | Description |
|------|-------------|
| *(none)* | Sync templates and restart dependent services |
| `--pull` | `git pull --ff-only` first |
| `--preserve-access` | Keep runtime per-group access modes in ios-xe-policy |
| `--rebuild-ssh-ops` | Rebuild `ssh-ops:latest` and restart GUI |
| `--no-restart` | File sync only |
| `--dry-run` | Print actions without applying |
| `-h`, `--help` | Show usage |

```bash
bash admin-access/refresh-clawlab-policies.sh --preserve-access
```

---

## MCP containers

### `ssh-ops-mcp/podctl.sh`

Manage ssh-ops Podman containers (GUI `:8765`, MCP `:8766` when `CLAWLAB_MANAGE_MCP=1`).

| Flag | Description |
|------|-------------|
| *(none)* | Ensure containers up |
| `--restart` | Restart in place |
| `--recreate` | Remove and recreate containers |
| `--build` | Rebuild image, then recreate |
| `--build --no-cache` | Clean rebuild |
| `--status` | Show status only |
| `--logs` | Append combined logs to log file |
| `--follow` | Stream logs after other actions |
| `-h`, `--help` | Show usage |

| Env | Description |
|-----|-------------|
| `CLAWLAB_MANAGE_MCP` | Set to `1` to manage MCP container (`:8766`) |
| `SSH_OPS_DIR` | Repo path to ssh-ops-mcp |
| `SSH_OPS_DATA` | Runtime data directory |

```bash
CLAWLAB_MANAGE_MCP=1 bash ssh-ops-mcp/podctl.sh --status
CLAWLAB_MANAGE_MCP=1 bash ssh-ops-mcp/podctl.sh --build --recreate
```

### `admin-access/heal-clawlab-stack.sh`

Post-install / on-demand repair for common lab breakages (502 on `/openclaw/`, MCP bind failures, incomplete DefenseClaw extension).

| Flag | Description |
|------|-------------|
| *(none)* | Report issues only |
| `--fix` | Restore extensions, refresh MCP quadlet, restart failed units |
| `--quiet` | Less output |

```bash
bash admin-access/heal-clawlab-stack.sh
bash admin-access/heal-clawlab-stack.sh --fix
bash install/verify-lab-portal.sh
```

Runs automatically at the end of `install-linux-lab.sh`, `configure-portal-mcp-auth.sh`, and `install-clawstack.sh` (non-local-full).

---

## Demos & policy tests

### `demo/clawlab-demo.sh`

Narrated walkthrough of good vs bad policy behavior.

| Flag | Description |
|------|-------------|
| *(none)* | Narrated (pauses between sections) |
| `--fast` | No pauses |
| `--probe-only` | DefenseClaw inspect probes only (no MCP) |
| `--agent` | Include optional agent turn |
| `--narrate` | Force narrated mode |
| `-h`, `--help` | Show usage |

| Env | Description |
|-----|-------------|
| `DEFENSECLAW_INSPECT_URL` | Sidecar URL (default `http://127.0.0.1:18970`) |
| `CLAWLAB_HOST` | Host label in output |

```bash
bash demo/clawlab-demo.sh --fast
```

### `tests/policy-test.sh`

Layered enforcement matrix (DefenseClaw, ssh-ops, optional agent E2E).

| Flag / env | Description |
|------------|-------------|
| *(none)* | Full run including slow agent cases |
| `--no-agent` | Fast deterministic probes only |
| `CLAWLAB_HOST` | Hostname label (default `lab-host`) |
| `CLAWLAB_MODEL` | Agent model for E2E section |

```bash
bash tests/policy-test.sh --no-agent
```

### `tests/scenario-approved-dc-block.sh`

Approved MCP change blocked when agent shortcuts via bash (see `docs/scenarios/`).

| Flag | Description |
|------|-------------|
| *(none)* | Local policy + DefenseClaw inspect probes |
| `--mcp-propose` | Also call live `propose_change` |

| Env | Description |
|-----|-------------|
| `CLAWLAB_SWITCH` | IOS-XE host name (default `C9300-24P`) |
| `DEFENSECLAW_INSPECT_URL` | Inspect API base URL |

### `tests/scenario-rbac-operator-block.sh`

Operator RBAC: blocked from sensitive reads; admin allowed.

| Flag | Description |
|------|-------------|
| *(none)* | Unit tests + live MCP probes |
| `--local-only` | Offline unit tests only |

| Env | Description |
|-----|-------------|
| `RBAC_OPERATOR_USER` | Operator username (default `alice`) |
| `RBAC_ADMIN_USER` | Admin username (default `admin`) |
| `CLAWLAB_SWITCH` | Network device host |
| `CLAWLAB_HOST` | Linux host for RBAC tests |

---

## Lab portal reinstall

For HTTPS portal issues on a Linux lab host, re-run the unified installer (replaces legacy `reset-lab-portal.sh`):

```bash
bash claw-portals/install-portals.sh --non-interactive --tls=https-le --auth=claw-auth
systemctl --user restart claw-auth defenseclaw-webgui openclaw-gateway
bash claw-auth/doctor.sh
```

---

## Archived (maintainer local only)

These paths are copied to **`_archive/`** (gitignored) and removed from the public tree.
Regenerate the local archive after checkout:

```bash
bash admin-access/populate-maintainer-archive.sh   # from a tree that still has the files
# or copy from _archive/README.md restore examples
```

| Path | Why archived |
|------|----------------|
| `admin-access/setup-admin-access.sh` | Superseded by `claw-portals/install-portals.sh` + claw-auth (already removed) |
| `admin-access/reset-lab-portal.sh` | Lab-host-specific; use portal installer + doctor instead (already removed) |
| `admin-access/fetch-ios-xe-command-reference.sh` | Large PDF fetch for policy authors (already removed) |
| `admin-access/render-architecture-diagram.sh` | Wrapper; use `python3 admin-access/render-*-diagram.py` (already removed) |
| `admin-access/alice/**` | Alice v1 training/benchmark tooling |
| `admin-access/training-network-specialist/**` | Maintainer network-specialist training tooling |
| `admin-access/scrub-public-release.py` | One-shot personal/lab identifier scrub before publish |
| `admin-access/apply-trusted-proxy.py` | Legacy OpenClaw trusted-proxy mode (clawlab uses `apply-token-portal.py`) |
| `admin-access/openclaw.trusted-proxy.json5` | Sample for trusted-proxy (not used with claw-auth portal) |
| `admin-access/pam-openclaw-admin` | Duplicate of `pam/openclaw-admin` |
| `admin-access/openclaw-admin.nginx.conf` | Duplicate of `nginx/openclaw-admin.conf` |
| `dhcp-sidecar/**` | Optional ISC DHCP sidecar deploy (Phase A); MCP DHCP tools remain in `ssh-ops-mcp/` |
| `isc-dhcp-mcp/README.md` | Phase C integration notes (superseded by `ssh-ops-mcp` DHCP tools) |
| `mcp-port/**` | Legacy quadlet path; use `quadlets/` or `ssh-ops-mcp/podctl.sh` |
| `model-tiering/**` | Unused OpenClaw model tiering sample |
| `claw-sysupdate/*.sh` | Fleet host updater install scripts (optional; systemd units remain in repo) |
