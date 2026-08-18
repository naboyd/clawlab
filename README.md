# clawlab

Self-hosted AI-ops lab: a governed **OpenClaw** agent with **Cisco DefenseClaw**
guardrails, a hardened **ssh-ops** MCP for network changes, a unified HTTPS admin
portal (**claw-auth**), and **Webex** alerting on policy violations.

> **Reference lab only.** This repository demonstrates integration patterns for
> OpenClaw + DefenseClaw + ssh-ops MCP. It is **not** a supported Cisco product.
> Run on isolated lab networks; see [SECURITY.md](SECURITY.md).

**Start here:** [docs/USER-GUIDE.md](docs/USER-GUIDE.md) ·
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) ·
**[Interactive diagrams](#diagrams)** (HTML)

---

## Diagrams

Open these in a browser after clone (tabbed flows work best locally — e.g.
`open docs/clawlab-system-internals.html` on macOS).

| Diagram | Interactive (HTML) | Static (PNG) |
|---------|-------------------|--------------|
| **How it works** — auth, MCP identity, gateway | [clawlab-system-internals.html](docs/clawlab-system-internals.html) | [PNG](docs/clawlab-system-internals.png) |
| **User journey** — install → sign-in → first change | [clawlab-user-journey.html](docs/clawlab-user-journey.html) | [PNG](docs/clawlab-user-journey.png) |
| **Architecture** — components and ports | [clawlab-architecture-overview.html](docs/clawlab-architecture-overview.html) | [PNG](docs/clawlab-architecture-overview.png) |
| **Policy enforcement** — propose → inspect → apply | [clawlab-policy-enforcement-flow.html](docs/clawlab-policy-enforcement-flow.html) | [PNG](docs/clawlab-policy-enforcement-flow.png) |
| **Command flow** — pass vs deny paths | [clawlab-command-flow-pass-deny.html](docs/clawlab-command-flow-pass-deny.html) | [PNG](docs/clawlab-command-flow-pass-deny.png) |
| **Demo & test matrix** — scenarios and expectations | [clawlab-demo-test-matrix.html](docs/clawlab-demo-test-matrix.html) | [PNG](docs/clawlab-demo-test-matrix.png) |

Regenerate after diagram edits:

```bash
python3 admin-access/render-system-internals-diagram.py
python3 admin-access/render-user-journey-diagram.py
python3 admin-access/render-architecture-overview-diagram.py
python3 admin-access/render-policy-flow-diagram.py
python3 admin-access/render-command-flow-diagram.py
python3 admin-access/render-demo-test-matrix-diagram.py
```

> **Secrets never live here.** Tokens, API keys, Fernet keys, and LE private keys stay
> on the host under `~/.openclaw`, `~/.defenseclaw`, `~/.claw-auth`, etc. Sanitized
> templates live in `config-templates/`.

---

## What this stack does

| Layer | Role |
|-------|------|
| **OpenClaw** | Agent gateway (`:18789`) — chat, tools, MCP clients |
| **DefenseClaw** | Prompt/tool inspect, regex + LLM judge, exec shims, audit |
| **ssh-ops MCP** | Read-only `run_command` + gated `propose_change` / `apply_change` |
| **MCP auth** | Per-user PATs (`skops_…`) via portal **MCP tokens**; see [ssh-ops-mcp/README.md](ssh-ops-mcp/README.md#connecting-other-ai-tools-cursor-claude-desktop-) |
| **Portal :8443** | Single URL — OpenClaw, MCP Admin, DefenseClaw policy editor |
| **claw-auth** | Shared login for all admin tabs (SQLite sessions) |

**Policy flow (summary):** Operator → agent proposes change → DefenseClaw blocks
bad tool/prompt patterns → ssh-ops validates IOS-XE allow groups → human approves
(four-eyes) → `apply_change` pushes config → Webex notifies on apply or block.

See **[Diagrams](#diagrams)** for all interactive HTML views and regenerate commands.

---

## Install order

Run on a **new host**. Each step is idempotent (safe to re-run).

### One-command wrappers (recommended)

| Platform | Script | Portal URL |
|----------|--------|------------|
| **macOS** | `bash install/install-mac.sh` | `http://127.0.0.1:8083/` |
| **Linux** (loopback dev) | `bash install/install-linux.sh` | `http://127.0.0.1:8083/` |
| **Linux lab server** | `bash install/install-linux-lab.sh` | `https://<host>:8443/` |

Add `--yes` for non-interactive installs. Linux lab: set `DOMAIN`, `LE_EMAIL`, and `LAN_IP`
before `install-linux-lab.sh --yes`.

### Manual steps (same result)

| Step | Script | What it does |
|------|--------|--------------|
| **1** | `install/preinstall-check.sh` | Node, pnpm, Ollama, DefenseClaw, podman checklist (`--fix` for apt/brew) |
| **2** | `install/install-clawstack.sh` | OpenClaw + DefenseClaw + guardrails; **`local-full`** = loopback portal `:8083`; **`local`** = agent only (pair with step 3 on lab hosts) |
| **3** | `claw-portals/install-portals.sh` | HTTPS nginx `:8443`, claw-auth, MCP identity `:8767`, skills + IOS archive | **Linux lab only** |

```bash
git clone https://github.com/naboyd/clawlab.git ~/clawlab
cd ~/clawlab

# macOS desktop (or Linux loopback dev)
bash install/install-mac.sh          # or: install-linux.sh on Linux
# non-interactive: bash install/install-mac.sh --yes

# Linux HTTPS lab host (icecream-style)
DOMAIN=lab.example.com LE_EMAIL=you@example.com LAN_IP=192.168.1.10 \
  bash install/install-linux-lab.sh --yes
```

**macOS:** `install-mac.sh` → bookmark `http://127.0.0.1:8083/`

**Linux lab server:** `install-linux-lab.sh` → bookmark `https://<host>:8443/` (Let's Encrypt via step 3 inside the wrapper)

**DefenseClaw scan backend** (step 2 prompt): **local** (Ollama Foundation-Sec judge), **cisco** (AI Defense API), or **both**.

For install checks, portal diagnostics, and policy refresh helpers, see
**[docs/Troubleshooting scripts.md](docs/Troubleshooting%20scripts.md)**.

**Full usage guide:** **[docs/USER-GUIDE.md](docs/USER-GUIDE.md)** — sign-in, OpenClaw pairing,
MCP auth, roles, change approval, troubleshooting.

---

## First login & OpenClaw device pairing

> Covered in detail in **[docs/USER-GUIDE.md](docs/USER-GUIDE.md)**. Quick reference:

> **Do this once per browser** after install. Same flow on **`local-full`** (`http://127.0.0.1:8083/`) and
> **lab server** (`https://<host>:8443/` with `install-portals.sh` + claw-auth).

| Step | Who | Action |
|------|-----|--------|
| **1** | Admin | Create portal user if none exists: `python claw-auth/manage.py create-user admin` |
| **2** | Anyone | Open the portal hub and sign in |
| **3** | Anyone | **OpenClaw** tab → **Open OpenClaw ↗** (includes `clawBind` for MCP identity + gateway token) |
| **4** | **Admin only** | **OpenClaw devices** tab → **Approve** the pending browser device |
| **5** | Anyone | Return to the OpenClaw Control UI — it should connect |

**MCP authentication**

| Client | Auth |
|--------|------|
| **OpenClaw** (from hub) | Portal `clawBind` → identity proxy `:8767` (no PAT needed) |
| **OpenClaw** (bookmarked chat URL) | Create PAT at hub → **MCP tokens** → `bash admin-access/set-openclaw-mcp-pat.sh` |
| **Cursor / Claude Desktop** | PAT `skops_…` → `https://<host>:8767/mcp` (see [ssh-ops-mcp/README.md](ssh-ops-mcp/README.md)) |

Do **not** bookmark plain `/openclaw/chat` without `clawBind` — `propose_change` requires verified identity.

**Admin-only tab:** The **OpenClaw devices** tab appears only for users with role **`admin`**
(manage roles via **Users** on the hub or `claw-auth/manage.py create-user alice --role operator`).
Non-admin operators see a banner asking them to contact an admin; they cannot approve devices.

**CLI fallback** (SSH on the gateway host):

```bash
openclaw devices list
openclaw devices approve <request-id>
```

**Verify local-full stack:** `bash install/verify-local-full.sh`

---

## Quick start

### macOS desktop stack (`local-full`)

After install, manage the loopback stack without systemd:

```bash
bash install/local-full-ctl.sh status
bash install/local-full-ctl.sh restart   # after config changes

# Verify stack
bash install/verify-local-full.sh

# Portal hub
open http://127.0.0.1:8083/
```

See **[First login & OpenClaw device pairing](#first-login--openclaw-device-pairing)** above for the full first-connect flow.

```bash
# First login user (if none yet)
~/.clawlab/venv/bin/python claw-auth/manage.py create-user admin
```

### Live demo (after stack is up)

```bash
bash demo/clawlab-demo.sh              # narrated walkthrough
bash demo/clawlab-demo.sh --fast       # no pauses
bash tests/policy-test.sh --no-agent   # full deterministic policy matrix
```

### Lab host redeploy

```bash
cd ~/clawlab && git pull
bash claw-portals/install-portals.sh --non-interactive --tls=https-le --auth=claw-auth
bash admin-access/configure-portal-mcp-auth.sh
systemctl --user restart claw-auth defenseclaw-webgui openclaw-gateway
podman build -t ssh-ops:latest ~/clawlab/ssh-ops-mcp && ~/clawlab/ssh-ops-mcp/podctl.sh --recreate
bash claw-auth/doctor.sh
```

After redeploy, use the same **[device pairing flow](#first-login--openclaw-device-pairing)** on `:8443`.

---

## Unified portal

| Tab | Path | Backend | Access |
|-----|------|---------|--------|
| OpenClaw Control UI | `/openclaw/` | `127.0.0.1:18789` | All signed-in users (token + device pairing) |
| **OpenClaw devices** | `/admin/openclaw-devices` | claw-auth → gateway `:18789` | **Admin only** — approve browser pairing |
| MCP Admin (ssh-ops) | `/ssh-ops/` | `127.0.0.1:8765` | All signed-in users |
| DefenseClaw policies | `/defenseclaw/` | `127.0.0.1:8770` | All signed-in users |

Default URL: `https://<host>:8443/` (HTTP lab: `:8083`). OpenClaw opens in a new
window; MCP Admin, DefenseClaw, and **OpenClaw devices** load in the hub via iframes.

**`local-full` vs lab server:** Device approval uses the same claw-auth UI and gateway API
on loopback (`127.0.0.1:18789`). Both `local-full` nginx (`:8083`) and `install-portals.sh`
(`:8443`, claw-auth mode) proxy `/admin/` to claw-auth. Requires claw-auth and the OpenClaw
gateway on the **same host** (standard install layout).

---

## Repository layout

### Install scripts (run in order)

| Script | Path |
|--------|------|
| 1 · Pre-install check | `install/preinstall-check.sh` |
| 2 · Core stack | `install/install-clawstack.sh` (`local` / **`local-full`** / `server`) |
| 2b · Local-full ctl | `install/local-full-ctl.sh` (start/stop portal + MCP on Mac) |
| 3 · HTTPS portal (lab) | `claw-portals/install-portals.sh` |

Shared helpers: `install/lib/clawlab-platform.sh` (OS detection, Node/pnpm, Ollama, DefenseClaw config patch).

### Other paths

| Path | Purpose |
|------|---------|
| `demo/` | **`clawlab-demo.sh`** — high-level good/bad behavior demo |
| `claw-auth/` | Centralized SQLite auth for admin portals |
| `ssh-ops-mcp/` | Hardened SSH MCP + admin GUI (Podman) |
| `defenseclaw-webgui/` | Policy editor (guardrail, rule packs, webhooks) |
| `defenseclaw-webex-bridge/` | Audit → Webex on HIGH/CRITICAL violations |
| `admin-access/` | Guardrail rules install, policy refresh, diagram render |
| `config-templates/` | Sanitized `openclaw.sample.json`, `defenseclaw.sample.yaml`, IOS-XE policy |
| `tests/` | Policy harness (`policy-test.sh`), scenario scripts |
| `docs/` | Architecture, scenarios, **interactive diagrams** (`.html` + `.png`) |
| `quadlets/` | Rootless Podman units for ssh-ops |
| `systemd-user/` | Gateway, cert renewal, shim heal, Webex bridge |
| `skills/` | `defenseclaw-canary`, `fleet-update`, `system-updater`, `ios-config-drift` |

---

## Bring-up (manual / piecemeal)

Prefer the **3-script install order** above. For ad-hoc assembly:

1. `bash install/preinstall-check.sh --fix`
2. `bash install/install-clawstack.sh` (or copy templates manually below)
3. Copy `config-templates/*.env.example` → real `.env` locations; fill secrets locally.
4. Copy `config-templates/openclaw.sample.json` → `~/.openclaw/openclaw.json`.
   Each provider needs a `models: [...]` array or the gateway crashes in failover.
5. Copy `config-templates/defenseclaw.sample.yaml` → `~/.defenseclaw/config.yaml`.
6. `bash claw-portals/install-portals.sh` for TLS + nginx + claw-auth.
7. `bash admin-access/install-clawlab-guardrail-rules.sh` for clawlab IOS-XE + CRUD rules.
8. `systemctl --user enable --now openclaw-gateway` (and ssh-ops quadlets / webgui as needed).

Pull judge model (local DefenseClaw backend):

```bash
ollama pull hf.co/fdtn-ai/Foundation-Sec-8B-Q8_0-GGUF:Q8_0
```

---

## LLM roles

| Role | Default |
|------|---------|
| OpenClaw agent primary | `ollama/llama3.1:8b` |
| Agent fallback | Anthropic Claude |
| DefenseClaw judge | Ollama Foundation-Sec-8B (or Cisco AI Defense when `scanner_mode: remote/both`) |

---

## Notes

- Admin UIs bind loopback; LAN access is via nginx + claw-auth on `:8443`.
- DefenseClaw enforces via fetch interceptor, sidecar inspect (`:18970`), and exec shims.
- IOS-XE changes use **60 granular `allow_groups`** — see `config-templates/ios-xe-policy.yaml`.
- After policy edits: `bash admin-access/refresh-clawlab-policies.sh --preserve-access`
  or Policy tab → Reload policy & restart gateways.
- **Troubleshooting:** [docs/Troubleshooting scripts.md](docs/Troubleshooting%20scripts.md) — script index with flags.
