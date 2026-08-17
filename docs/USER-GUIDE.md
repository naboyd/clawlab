# clawlab usage guide

How to install, sign in, and use the clawlab portal, OpenClaw agent, MCP tools, and
change-approval workflow.

> **Reference lab only** — not a supported Cisco product. Run on isolated lab networks.
> See [SECURITY.md](../SECURITY.md).

**Diagrams**

| View | PNG | HTML |
|------|-----|------|
| **User journey** (start here) | [clawlab-user-journey.png](clawlab-user-journey.png) | [clawlab-user-journey.html](clawlab-user-journey.html) |
| **How it works** (auth & data flow) | [clawlab-system-internals.png](clawlab-system-internals.png) | [clawlab-system-internals.html](clawlab-system-internals.html) |
| Component map | [clawlab-architecture-overview.png](clawlab-architecture-overview.png) | [clawlab-architecture-overview.html](clawlab-architecture-overview.html) |
| Policy enforcement | [clawlab-policy-enforcement-flow.png](clawlab-policy-enforcement-flow.png) | [clawlab-policy-enforcement-flow.html](clawlab-policy-enforcement-flow.html) |

Technical deep dive: [ARCHITECTURE.md](ARCHITECTURE.md)

Regenerate diagrams:

```bash
python3 admin-access/render-user-journey-diagram.py
python3 admin-access/render-system-internals-diagram.py
python3 admin-access/render-architecture-overview-diagram.py
python3 admin-access/render-policy-flow-diagram.py
```

---

## What you get

One bookmark opens a **portal hub** with tabs for:

| Tab | What it is | Who uses it |
|-----|------------|-------------|
| **MCP Admin** | ssh-ops host inventory, changes, policy | All signed-in users |
| **DefenseClaw** | Guardrail rules, suppressions, webhooks | All signed-in users |
| **Open OpenClaw ↗** | Agent chat (opens new window) | All signed-in users |
| **OpenClaw devices** | Approve browser pairing | **Admin** only |
| **Users** | Create users, roles, Webex email | **Admin** only |
| **MCP tokens** | Personal access tokens for external MCP clients | All users (own tokens; superadmin manages all) |

Behind the scenes: **OpenClaw** runs the agent, **DefenseClaw** inspects prompts and tools,
**ssh-ops MCP** executes read-only commands and gated config changes on IOS-XE devices.

---

## Install (new host)

Run in order:

```bash
git clone https://github.com/naboyd/clawlab.git ~/clawlab
cd ~/clawlab

bash install/preinstall-check.sh --fix
bash install/install-clawstack.sh --local-full    # Mac desktop
# or: bash install/install-clawstack.sh           # Linux agent stack

bash claw-portals/install-portals.sh              # Linux HTTPS :8443 (skip on Mac local-full)
```

| Platform | Portal URL | Install path |
|----------|------------|--------------|
| **macOS** | `http://127.0.0.1:8083/` | Steps 1 → 2 with `--local-full` |
| **Linux lab** | `https://<host>:8443/` | Steps 1 → 2 → 3 |

After Linux portal install, MCP auth is wired automatically when using **claw-auth**
(`configure-portal-mcp-auth.sh` runs at the end of `install-portals.sh`).

---

## First-time setup

### 1. Create an admin user

If no users exist yet:

```bash
python3 ~/clawlab/claw-auth/manage.py create-user admin
# optional role: --role superadmin
```

### 2. Sign in to the portal

Open the hub URL and log in with claw-auth (username + password).

### 3. Connect OpenClaw (once per browser)

| Step | Who | Action |
|------|-----|--------|
| 1 | Anyone | Hub → **Open OpenClaw ↗** (link includes gateway token + `clawBind` for MCP identity) |
| 2 | **Admin** | Hub → **OpenClaw devices** → **Approve** the pending browser |
| 3 | Anyone | Return to OpenClaw — it should connect |

**CLI fallback** (on the gateway host):

```bash
openclaw devices list
openclaw devices approve <request-id>
```

### 4. Verify the stack

```bash
bash ~/clawlab/install/verify-local-full.sh   # Mac local-full
bash ~/clawlab/claw-auth/doctor.sh            # portal auth health
```

---

## Daily use by role

### Operator

1. **Sign in** at the portal hub.
2. **Open OpenClaw** from the hub (not a stale bookmark).
3. **Chat with the agent** — ask it to show device state or propose IOS-XE changes.
4. **Approve changes** you did not propose (four-eyes) via Webex adaptive card or portal
   **MCP Admin → Changes**.
5. Use **MCP Admin** for host inventory and change status (read-only tabs as allowed by role).

Operators cannot approve their own proposed changes.

### Admin

Everything operators can do, plus:

- **OpenClaw devices** — approve new browsers
- **Users** — create users, set roles (`operator` / `admin` / `superadmin`), link Webex email
- **DefenseClaw** — edit guardrail rules, suppressions, webhook settings
- **MCP Admin → Policy** — set per-group deny / approve / allow modes
- **Reload policy** after edits (Policy tab or `refresh-clawlab-policies.sh`)

### Superadmin

Same as admin, plus manage **MCP tokens** for any user (hub → **MCP tokens**).

---

## MCP authentication (important)

clawlab uses **different auth** for the portal vs MCP tool calls.

| Client | How to authenticate | Notes |
|--------|---------------------|-------|
| **Portal tabs** | claw-auth session cookie | Sign in once at the hub |
| **OpenClaw from hub** | `clawBind` query param → identity proxy `:8767` | **Recommended** — no PAT needed |
| **OpenClaw bookmark** | PAT (`skops_…`) in `openclaw.json` | Only if you bookmark `/openclaw/chat` without `clawBind` |
| **Cursor / Claude Desktop** | PAT on `https://<host>:8767/mcp` | Create at hub → **MCP tokens** |
| **OpenClaw Control UI** | Gateway token in URL + device pairing | Separate from MCP auth |

**Do not** connect external clients to raw MCP on `:8766` — use the **identity proxy on `:8767`**.

### Create a PAT (Cursor / external tools)

1. Sign in to the portal hub.
2. Open **MCP tokens**.
3. Create a token (`skops_…`).
4. Configure your MCP client:

   ```http
   URL: https://<your-host>:8767/mcp
   Authorization: Bearer skops_…
   ```

See [ssh-ops-mcp/README.md](../ssh-ops-mcp/README.md) for client-specific steps.

### Bookmarked OpenClaw chat URL (no clawBind)

If you saved a plain OpenClaw chat URL without the hub link:

1. Create a PAT at hub → **MCP tokens**.
2. Run:

   ```bash
   bash ~/clawlab/admin-access/set-openclaw-mcp-pat.sh
   systemctl --user restart openclaw-gateway
   ```

Without verified identity, `propose_change` will fail RBAC checks.

---

## Change approval workflow (four-eyes)

Typical flow when an operator asks the agent to change a switch:

1. Agent calls **DefenseClaw** — bad prompts/tools blocked before MCP.
2. Agent calls **propose_change** on ssh-ops MCP — IOS-XE policy validates allow groups.
3. Change appears as **pending** — Webex card and/or MCP Admin **Changes** tab.
4. A **different** user (or mapped Webex identity) **approves**.
5. Agent or operator runs **apply_change** — backup, push, verify, write mem.
6. **Webex** notifies on blocks, approvals, and applies.

Detail: [clawlab-policy-enforcement-flow.html](clawlab-policy-enforcement-flow.html)

---

## Portal reference

| Path | Backend | Auth |
|------|---------|------|
| `/` | Hub | Session |
| `/_claw_auth/*` | Login / verify | — |
| `/ssh-ops/` | MCP Admin GUI | Session via nginx |
| `/defenseclaw/` | Policy editor | Session via nginx |
| `/openclaw/` | OpenClaw gateway | Gateway token (no nginx session) |
| `/admin/openclaw-devices` | Device pairing UI | Session (admin) |
| `/mcp/tokens/ui` | PAT management | Session |

Default URLs:

- Production: `https://<host>:8443/`
- Mac local-full: `http://127.0.0.1:8083/`

---

## Managing the stack

### macOS local-full

```bash
bash ~/clawlab/install/local-full-ctl.sh status
bash ~/clawlab/install/local-full-ctl.sh restart
bash ~/clawlab/install/verify-local-full.sh
```

### Linux lab host (upgrade)

```bash
cd ~/clawlab && git pull
bash claw-portals/install-portals.sh --non-interactive --tls=https-le --auth=claw-auth
bash admin-access/configure-portal-mcp-auth.sh
systemctl --user restart claw-auth defenseclaw-webgui openclaw-gateway
podman build -t ssh-ops:latest ~/clawlab/ssh-ops-mcp && ~/clawlab/ssh-ops-mcp/podctl.sh --recreate
bash claw-auth/doctor.sh
```

### User management

```bash
python3 ~/clawlab/claw-auth/manage.py create-user alice --role operator
python3 ~/clawlab/claw-auth/manage.py set-webex-email alice alice@cisco.com
python3 ~/clawlab/claw-auth/manage.py list-users
```

Roles:

| Role | User admin | MCP RBAC | Cross-user PATs |
|------|------------|----------|-----------------|
| `operator` | — | read / filtered show, propose | own only |
| `admin` | yes | full MCP admin | own only |
| `superadmin` | yes (+ assign superadmin) | full MCP admin | all users |

---

## Demo and testing

```bash
bash ~/clawlab/demo/clawlab-demo.sh              # narrated walkthrough
bash ~/clawlab/demo/clawlab-demo.sh --fast
bash ~/clawlab/tests/policy-test.sh --no-agent   # deterministic policy matrix
```

---

## Troubleshooting

| Symptom | Check |
|---------|-------|
| `install-ios-config-archive.sh`: No such file | Wrong clone or branch — use repo with `ios-config-drift` (`~/AI/clawlab` vs `~/clawlab`) |
| Portal 401 loop | `bash claw-auth/doctor.sh`; verify nginx `auth_request` |
| OpenClaw WebSocket fails | Use hub link; confirm `/openclaw/` not redirected; `apply-token-portal.py` |
| Device never connects | Admin must approve on **OpenClaw devices** tab |
| MCP 401 invalid token | Use `:8767` not `:8766`; PAT from hub; token not expired |
| propose_change denied identity | Open from hub (`clawBind`) or set PAT via `set-openclaw-mcp-pat.sh` |
| Policy change not enforced | Policy tab → Reload; or `refresh-clawlab-policies.sh` |

Full script index: [Troubleshooting scripts.md](Troubleshooting%20scripts.md)

Print OpenClaw Control UI URL:

```bash
bash ~/clawlab/admin-access/print-gateway-url.sh
```

---

## IOS config archive & drift detection

The **`ios-config-drift`** skill (plus MCP tools) archives Cisco IOS running-configs and
alerts when changes appear **outside** the MCP change log (console edits, unauthorized access).

**Installed automatically** by `install-clawstack.sh` / `install-portals.sh` via
`admin-access/install-clawlab-extras.sh` (skills symlink + daily scheduler).

| Item | Location |
|------|----------|
| Skill | `skills/ios-config-drift/SKILL.md` → linked into `~/.openclaw/workspace/skills/` |
| Archives | `~/.clawlab/ssh-ops/data/ios-config-archive/{host}/` |
| MCP tools | `check_ios_config_drift()`, `get_ios_config_archive_status(host=…)` |
| Manual CLI | `python3 ssh-ops-mcp/scripts/ios-config-drift-check.py` |

**Re-install extras** (skills + scheduler; creates `~/.clawlab/venv` if missing):

```bash
cd ~/AI/clawlab
bash admin-access/install-clawlab-extras.sh
```

**One-off drift check:**

```bash
cd ~/AI/clawlab
bash claw-portals/ensure-venv.sh
~/.clawlab/venv/bin/python3 ssh-ops-mcp/scripts/ios-config-drift-check.py
~/.clawlab/venv/bin/python3 ssh-ops-mcp/scripts/ios-config-drift-check.py --host SWITCHNAME
```

Hosts tagged `no_config_archive` are skipped; `config_archive` forces inclusion.

**Scheduler:** systemd user timer on Linux; LaunchAgent on macOS (~04:00 local).

> **Repo path:** Your clone is at **`~/AI/clawlab`** (there is no `~/clawlab` on this Mac).
> Run all commands from that directory. Do not paste comment lines starting with `#`.

---

## Future: Duo SSO

Enterprise SSO (Duo OIDC) is **not implemented** yet. Planning doc:
[duo-sso-integration.md](duo-sso-integration.md)

---

## Related docs

- [ARCHITECTURE.md](ARCHITECTURE.md) — ports, services, design decisions
- [claw-portals/README.md](../claw-portals/README.md) — portal installer
- [claw-auth/README.md](../claw-auth/README.md) — auth service
- [ssh-ops-mcp/README.md](../ssh-ops-mcp/README.md) — MCP server and PAT setup
