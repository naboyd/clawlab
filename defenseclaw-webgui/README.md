# DefenseClaw policy editor

Web UI to view and edit DefenseClaw policies without hand-editing YAML on the
host. Follows the same patterns as `ssh-ops-mcp/webgui.py`: Flask, loopback
bind, secrets never displayed, optional nginx+PAM for LAN access.

## What you can edit

| Tab | Files / settings |
|-----|------------------|
| **Overview** | Current posture, validate, reload gateway |
| **Guardrail** | `guardrail.*` in `config.yaml` — mode, rule pack, judge toggles |
| **Rule pack** | YAML under `guardrail.rule_pack_dir` — suppressions, custom rules |
| **Actions** | `skill_actions`, `mcp_actions`, `plugin_actions`; activate OPA policy |
| **Webhooks** | `webhooks[]` in config (tokens via `secret_env` only) |
| **Firewall** | `firewall.yaml` egress policy |
| **IOS-XE policy** | `config-templates/ios-xe-policy.yaml` — device config allow_groups |
| **Audit** | Read-only tail of `audit.db` |
| **Advanced** | Full `config.yaml` editor |

## Install (recommended — all portals)

Use the unified installer for TLS + centralized auth + nginx:

```bash
cd claw-portals
chmod +x install-portals.sh
./install-portals.sh
```

## Install (loopback only)

```bash
cd defenseclaw-webgui
chmod +x install-webgui.sh
./install-webgui.sh
```

Open http://127.0.0.1:8770

## Manual run

```bash
pip install -r requirements.txt
export DEFENSECLAW_CONFIG=~/.defenseclaw/config.yaml   # optional
python webgui.py
```

## LAN exposure (optional, sudo)

Copy `../nginx/defenseclaw-admin.conf` into nginx `sites-enabled`, adjust the
LE cert paths and listen IP, then reload nginx. Uses the same PAM service as the
ssh-ops admin GUI (`openclaw-admin`).

Default port: **8445** → proxies to `127.0.0.1:8770`.

## After saving changes

| Change | Reload |
|--------|--------|
| Guardrail settings, actions, webhooks | Gateway reload (button on Overview) |
| Rule pack YAML files | Gateway reload |
| OPA named policy | **Activate policy** on Actions tab, or `defenseclaw policy activate <name>` |
| `firewall.yaml` | DefenseClaw recompiles on next apply (gateway reload) |
| `ios-xe-policy.yaml` | **Merge into DefenseClaw rule pack** on IOS-XE tab, then gateway reload |

Run the `defenseclaw-canary` skill after policy changes to verify enforcement
and Webex alerting.

## Security notes

- Binds to `127.0.0.1` by default — not reachable from the network.
- `.env` secret values are never rendered; webhook UI shows set/missing only.
- Saved config and policy files are chmod `0600`.
- For production LAN access, always use nginx+PAM — do not bind `0.0.0.0` without auth.

## Environment

| Variable | Default |
|----------|---------|
| `DEFENSECLAW_HOME` | `~/.defenseclaw` |
| `DEFENSECLAW_CONFIG` | `~/.defenseclaw/config.yaml` |
| `DEFENSECLAW_ENV` | `~/.defenseclaw/.env` |
| `DEFENSECLAW_GUI_HOST` | `127.0.0.1` |
| `DEFENSECLAW_GUI_PORT` | `8770` |
| `CLAWLAB_REPO` | `~/clawlab` (ios-xe-policy.yaml location) |
| `IOS_XE_POLICY_PATH` | override canonical policy file path |
