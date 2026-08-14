# ssh-ops MCP server

A small Model Context Protocol (MCP) server that gives an MCP client (like
Claude) **safe, allowlisted SSH access** to a fixed set of Linux hosts. Built
for digging through logs and diagnosing servers that keep going down, with an
opt-in ability to restart specific named services.

It runs on **your** machine or infra. Your SSH keys and host inventory stay
local — the client only ever receives the tool *results*.

## What it can do

| Tool | What it does | Mutating? |
|------|--------------|-----------|
| `list_hosts` | Lists configured hosts, `tags`, flags (`allow_write`, `auto_update`), and restartable services | No |
| `run_command` | Runs a **read-only** allowlisted command (logs, dmesg, df, ps, ss, `systemctl status`, …) | No |
| `tail_log` | Tails the last N lines of a log file | No |
| `get_journal` | Queries the systemd journal (filter by unit, since, priority, boot) | No |
| `check_health` | Bundle: uptime, memory, disk, reboots, failed units, OOM-killer hits | No |
| `restart_service` | Restarts a service **only if** it's allowlisted for that host | **Yes** |
| `run_write_command` | Runs an **arbitrary** command — only on hosts with `allow_write: true` | **Yes** |
| `upload_file` | SFTP a file from the transfers dir to a host (needs `allow_write`) | **Yes** |
| `download_file` | SFTP a file from a host into the transfers dir | No (remote read) |

## Write access & file transfer

Read-only is the default. Two things are gated behind a per-host opt-in:

- **`run_write_command`** runs an arbitrary, un-allowlisted command — but only on
  hosts that set `allow_write: true` (toggle in the GUI). There's no command
  filter, so it can modify or delete data; every call is audit-logged. Network
  devices are refused (device config goes through the network agent).
- **`upload_file` / `download_file`** move files over SFTP, confined on the
  container side to a **transfers sandbox** (`transfers_dir`, default
  `/data/transfers`, size-capped by `max_transfer_mb`). Path traversal is
  rejected — `local_name` must be a plain filename under that dir. Uploads need
  `allow_write`; downloads only read the remote. Since the sandbox lives on the
  mounted `/data` volume, downloaded files are visible on the host.

Enable per host in `hosts.yaml` (`allow_write: true`) or the GUI checkbox. Leave
it off for anything you want kept strictly read-only.

## Host tags

Each host may carry a `tags` list (comma-separated in the GUI). `list_hosts`
returns `tags: ["web", "prod", …]` so OpenClaw skills and other flows can
select hosts by tag (platform filters still apply).

Legacy `description` fields are migrated on read: a single description becomes
one tag; comma-separated descriptions become multiple tags.

Example `list_hosts` entry:

```json
{
  "name": "web1",
  "kind": "linux",
  "tags": ["web", "prod", "auto_update"],
  "allow_write": true,
  "auto_update": true
}
```

## Fleet auto-update flag

Linux hosts can be flagged for patching via the **Auto-update** checkbox (adds
the `auto_update` tag) or by including `auto_update` in **Tags**. The
`fleet-update` skill uses `list_hosts` and selects linux hosts where
`auto_update` is true.

Requirements per auto-update host:

- `auto_update: true` or `auto_update` in `tags`
- `allow_write: true` (needed for `systemctl start claw-sysupdate.service`)
- `claw-sysupdate` installed on the target with scoped passwordless sudo

See `claw-sysupdate/` (systemd units) and `skills/fleet-update/SKILL.md`. The shell
installer was moved to local `_archive/`; fleet hosts need the updater script installed manually or restored from archive.

## Security model

- **Read-only by default.** `run_command` permits only commands whose first
  token (per pipe segment) is on a fixed allowlist of diagnostic binaries.
  Shell chaining/redirection/substitution (`;  &&  ||  \`  $()  >  <  &`) is
  rejected. Pipes to tools like `grep` are allowed.
- **`systemctl` via `run_command` is status-only.** Restarts go exclusively
  through `restart_service`, which checks the host's `allowed_services`.
- **Per-host scope.** The server can only reach hosts defined in the config.
- **Audit log.** Every call (including rejected ones) is written to
  `settings.audit_log` and echoed to stderr.
- **Least privilege on the hosts.** Use a dedicated low-privilege account.
  If you enable `restart_service`, grant *passwordless sudo for only those
  specific units* via a narrow sudoers rule, e.g.:
  ```
  deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart nginx, /usr/bin/systemctl restart myapp
  ```

## Setup

```bash
cd ssh_ops_mcp
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp hosts.example.yaml hosts.yaml
# edit hosts.yaml: hostnames, usernames, key paths, allowed_services
export SSH_OPS_CONFIG=$(pwd)/hosts.yaml

# make sure each host is in known_hosts (host_key_policy: reject needs this)
ssh-keyscan -H 10.0.0.11 >> ~/.ssh/known_hosts   # repeat per host

python server.py   # starts on stdio
```

## Register it as a connector

Add it to your MCP client config. Example (Claude Desktop /
`claude_desktop_config.json` style):

```json
{
  "mcpServers": {
    "ssh-ops": {
      "command": "/absolute/path/to/ssh_ops_mcp/.venv/bin/python",
      "args": ["/absolute/path/to/ssh_ops_mcp/server.py"],
      "env": {
        "SSH_OPS_CONFIG": "/absolute/path/to/ssh_ops_mcp/hosts.yaml"
      }
    }
  }
}
```

Restart the client; the `ssh-ops` tools will appear. Then you can ask things
like *"check_health on all hosts"* or *"get the previous-boot journal errors
from db1"* and I'll pull them.

## Sudo passwords (encrypted) + web GUI

Restarts use `sudo -S`, reading the password from stdin. Passwords are stored
**encrypted** and never appear in `hosts.yaml`, the audit log, or tool output.

How it works:

- `secrets_store.py` encrypts each password with **Fernet** and writes the
  ciphertext to `.env` (0600). The symmetric key lives in a **separate keyfile**
  (`~/.ssh_ops/master.key` by default, 0600), auto-generated on first use.
  Decryption needs *both* files — so keep the keyfile off any repo/backup that
  also holds `.env`. (`.gitignore` already excludes both.)
- At restart time the server decrypts the password in memory and pipes it to
  `sudo -S -p ''`. If no password is stored it falls back to `sudo -n`
  (passwordless). Hosts with `Defaults requiretty` can set `use_pty: true`.

### Manage hosts + secrets in the browser

```bash
export SSH_OPS_CONFIG=$(pwd)/hosts.yaml   # same file the MCP server reads
python webgui.py                          # -> http://127.0.0.1:8765
```

The GUI is bound to `127.0.0.1` only (not reachable from the network) and lets
you add/edit/delete hosts and set each host's sudo password. Passwords are
encrypted on save; the page only shows a "set / none" indicator, never the value.
Leaving the password field blank on edit keeps the existing secret.

You can also manage secrets from the CLI:

```bash
python secrets_store.py set web1 'the-password'
python secrets_store.py list
python secrets_store.py del web1
```

### Environment variables

| Var | Purpose | Default |
|-----|---------|---------|
| `SSH_OPS_CONFIG` | host inventory YAML | `./hosts.yaml` |
| `SSH_OPS_KEYFILE` | master encryption key | `~/.ssh_ops/master.key` |
| `SSH_OPS_ENV` | encrypted secrets file | `./.env` |
| `SSH_OPS_GUI_PORT` | GUI port | `8765` |

## Network devices (Cisco IOS-XE, NX-OS, etc.)

Hosts aren't limited to Linux. Set a `platform` on a host and it's treated as a
network device, reached with **netmiko** instead of a POSIX shell — it handles
password login, `enable` (privileged mode), and paging automatically.

```yaml
sw1:
  platform: cisco_ios      # ios / ios-xe -> cisco_ios; also cisco_nxos, cisco_asa, arista_eos, juniper_junos
  hostname: 10.0.0.2
  username: netadmin
  # login + enable passwords are stored ENCRYPTED (GUI or secrets_store.py), not here
```

- **Auth:** username + **login password** + **enable password**, both encrypted
  in `.env` just like sudo passwords. Add them in the GUI (the platform dropdown
  reveals the two fields) or via CLI:
  ```bash
  python secrets_store.py set sw1 ...        # sudo (Linux)  — for network use:
  python -c "import secrets_store as s; s.set_secret('sw1','login','pw'); s.set_secret('sw1','enable','enpw')"
  ```
- **Read-only:** on network hosts `run_command` permits only `show`, `dir`,
  `ping`, `traceroute` (and IOS-style filters, e.g. `show run | include ntp`).
  Config/write/reload/erase are rejected. The Linux-only tools (`check_health`,
  `get_journal`, `tail_log`, `restart_service`) return a clear message if called
  against a network device.

Example once connected: `run_command(host="sw1", command="show version")` or
`run_command(host="sw1", command="show logging | include LINK")`.

## Podman (recommended for a Linux host)

The same image runs under Podman with no changes (`podman build`, `podman run`).
On a Linux host this is the nicest option: rootless, no daemon, no VM — the
container reaches your LAN directly and mounts `~/.ssh` natively.

### Build + run the GUI

```bash
cd ssh_ops_mcp
./run-podman.sh          # builds ssh-ops:latest and starts the GUI on 127.0.0.1:8765
```

Or run it as a rootless systemd service (survives logout) using the included
Quadlet unit — see `podman/ssh-ops-gui.container` for the install steps.

### Register the MCP server with your client / agent

```json
{
  "mcpServers": {
    "ssh-ops": {
      "command": "podman",
      "args": [
        "run", "--rm", "-i",
        "-v", "/home/USER/ssh_ops_mcp/data:/data:Z",
        "-v", "/home/USER/.ssh:/root/.ssh:ro,Z",
        "ssh-ops:latest", "mcp"
      ]
    }
  }
}
```

Notes for Podman on Linux:

- **Remote MCP:** set `SSH_OPS_MCP_REMOTE=1` before `./podctl.sh --recreate` to
  publish on `0.0.0.0:8766` with TLS (auto-detects lego certs from `DOMAIN` in
  `~/.claw-portals/config.env`). Clients use `https://your-host:8766/mcp` with a
  Bearer token from the ssh-ops admin GUI.
- **`:Z`** on volume mounts relabels them for SELinux (needed on Fedora/RHEL).
  Drop it on non-SELinux systems if it causes trouble.
- **LAN reachability:** rootless Podman's default network (pasta/slirp4netns)
  routes outbound to your LAN fine. If a device is unreachable, add
  `--network host` to the `mcp` run args.
- **Keys:** container paths still apply — set `key_path: /root/.ssh/id_ed25519`,
  or skip keys entirely and use encrypted login/enable passwords from the GUI.

## Config hot-reload

The server re-reads `hosts.yaml` when it changes on disk (mtime-checked per
call). Add or edit a host in the GUI and the MCP picks it up on the next tool
call — **no server/app restart needed**. (Encrypted secrets in `.env` are also
read live.) Only changes to `settings` — audit log path, timeouts — still
require a restart.

### Diagnostics

If the MCP container keeps restarting (`Up 1 second` in `podman ps`), run:

```bash
bash ssh-ops-mcp/doctor.sh
```

It checks for `hosts.yaml` in the active data dir (default `~/.clawlab/ssh-ops/data`),
warns if config still lives in the legacy `~/ssh_ops_mcp/data` path, and tails MCP
logs for the usual crash cause.

## Docker

The image runs in two modes via the entrypoint: `gui` (the config UI, default)
and `mcp` (the MCP server on stdio, launched by your client).

All state lives in a mounted `./data` dir (`hosts.yaml`, `.env`, `master.key`,
audit log), and your SSH keys are mounted read-only. **Important:** inside the
container keys live at `/root/.ssh/...`, so set each host's `key_path` to the
*container* path, e.g. `/root/.ssh/id_ed25519`.

### 1. Build + run the GUI

```bash
mkdir -p data
docker compose up --build      # GUI at http://127.0.0.1:8765
```

The compose file publishes the port to `127.0.0.1` only. Add your hosts and
sudo passwords in the browser; they're written (encrypted) into `./data`.

Populate known_hosts once (required by `host_key_policy: reject`):

```bash
docker compose run --rm gui ssh-keyscan -H 10.0.0.11 >> data/known_hosts
# then mount data/known_hosts, or add it to your ~/.ssh/known_hosts
```

### 2. Register the MCP server with your client

The client launches a fresh container per session on stdio:

```json
{
  "mcpServers": {
    "ssh-ops": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-v", "/ABS/PATH/ssh_ops_mcp/data:/data",
        "-v", "/home/youruser/.ssh:/root/.ssh:ro",
        "ssh-ops:latest", "mcp"
      ]
    }
  }
}
```

Build the image first (`docker compose build` or `docker build -t ssh-ops:latest .`)
so `ssh-ops:latest` exists. Use absolute paths in the client config.

### Using ssh-agent instead of mounting keys

If you'd rather not mount private keys, mount the agent socket and set
`allow_agent: true` (default) in your hosts:

```
-v $SSH_AUTH_SOCK:/ssh-agent -e SSH_AUTH_SOCK=/ssh-agent
```

## Webex four-eyes approval

When a change is **proposed**, ssh-ops can post an adaptive card to your configured
Webex room with **Approve** and **Reject** buttons (four-eyes: approver must be a
*different* claw-auth user than the proposer).

### Prerequisites

1. Webex bot token and room in `~/.defenseclaw/config.yaml` with `change` in `events`
2. Link each approver's Webex email in claw-auth (`manage.py set-webex-email` or Admin → Users)
3. Mount `DEFENSECLAW_HOME` into the ssh-ops container (see `podctl.sh` / quadlets)
4. nginx exposes `/ssh-ops/webex/hooks/` **without** claw-auth (HMAC-verified instead)

### Inbound webhook (card buttons)

Register at [developer.webex.com](https://developer.webex.com):

| Field | Value |
|-------|-------|
| Resource | `attachmentActions` |
| Event | `created` |
| Target URL | `https://YOUR-HOST:8443/ssh-ops/webex/hooks/attachment-actions` |

Save the webhook secret to `~/.defenseclaw/.env`:

```bash
WEBEX_APPROVAL_WEBHOOK_SECRET=...
```

Optional:

| Variable | Purpose |
|----------|---------|
| `WEBEX_APPROVAL_CARDS` | `0` to disable adaptive cards (markdown + signed links only) |
| `WEBEX_APPROVAL_PUBLIC_URL` | Override webhook URL if auto-detect fails |
| `WEBEX_ACTION_SECRET` | HMAC secret for signed portal approve/reject links (defaults to `CLAWLAB_INTERNAL_TOKEN`) |
| `CLAW_PORTAL_SSH_OPS_URL` | Base URL for portal links, e.g. `https://host:8443/ssh-ops` |

### Signed portal fallback

Proposed-change messages include signed **Approve in browser** / **Reject** links.
These hit `/ssh-ops/webex/action?token=...`, require claw-auth login, and enforce
the same four-eyes rules as the Webex card.

### Test

```bash
python3 tests/test_webex_approval.py
```

## Connecting other AI tools (Cursor, Claude Desktop, …)

OpenClaw uses short-lived `X-Claw-Mcp-Bind` tokens from the portal hub. Other MCP
clients should use a **personal access token (PAT)**:

1. Sign in to the portal hub → **MCP tokens** (or `POST /_claw_auth/mcp/tokens` with session cookie).
2. Create a token — copy the `skops_…` value immediately (shown once).
3. Point your MCP client at the ssh-ops URL and send:

```json
{
  "headers": {
    "Authorization": "Bearer skops_YOUR_TOKEN_HERE"
  }
}
```

Example (remote lab with TLS):

```text
https://icecream.example.com:8766/mcp
Authorization: Bearer skops_…
```

**Migration:** if you previously used the shared MCP bearer token plus a self-asserted
`X-Auth-User` header, switch to a PAT — spoofed identity headers from untrusted clients
are no longer honored. To allow a front-end proxy (portal/nginx) to forward identity,
set `SSH_OPS_TRUSTED_PROXY_IPS` to its IP(s), comma-separated.

`X-Claw-Mcp-Bind` remains supported for OpenClaw.

## Extending

- Add binaries to `READ_ONLY_BINARIES` in `server.py` to widen diagnostics.
- Add services to a host's `allowed_services` to permit more restarts.
- The connection opens fresh per call for simplicity; add pooling if you have
  many hosts or call it very frequently.
