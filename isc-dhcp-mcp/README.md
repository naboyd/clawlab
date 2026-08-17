# isc-dhcp MCP (Phase C)

Phase C adds **ISC DHCP include management** to the existing **ssh-ops MCP** on icecream.
There is no separate MCP process — DHCP tools live alongside IOS change tools and share
the same four-eyes approval queue in MCP Admin.

## Architecture

```
Agent (OpenClaw / Claude)
    → ssh-ops MCP (icecream)
        → propose_change(change_type=dhcp_include)
        → human approves in MCP Admin
        → apply_change(change_id)
            → SSH + curl → dhcp-sidecar (127.0.0.1:9080 on Services/Nuc03)
                → dhcpd -t → write include → restart isc-dhcp-server
```

## MCP tools (DHCP)

| Tool | Purpose |
|------|---------|
| `list_dhcp_hosts` | Hosts tagged `dhcp` with sidecar metadata |
| `list_dhcp_includes` | List `/etc/dhcp/dhcpd.d/*.conf` via sidecar |
| `get_dhcp_include` | Read one include file |
| `validate_dhcp_include` | `dhcpd -t` dry-run (no write) |
| `propose_change` | `change_type=dhcp_include` enters approval queue |
| `get_change` / `list_changes` | Queue status |
| `apply_change` / `rollback_change` | After approval |

### `dhcp_include` spec

```json
{
  "include_name": "vlan100.conf",
  "content": "subnet 10.100.0.0 netmask 255.255.255.0 {\n  range 10.100.0.50 10.100.0.200;\n}\n"
}
```

`include_name` may also be passed as `name`. Content is validated at propose time via the
sidecar (`dhcpd -t`).

## Host inventory

Add tag `dhcp` to DHCP servers in `~/.clawlab/ssh-ops/data/hosts.yaml`:

```yaml
hosts:
  Services:
    tags: [linux, dhcp]
    hostname: services.naboydciscolab.com
    username: sshops
    key_path: /root/.ssh/ssh-ops-mcp
    platform: linux
  Nuc03:
    tags: [linux, dhcp]
    hostname: 192.168.128.15
    username: sshops
    key_path: /root/.ssh/ssh-ops-mcp
    platform: linux
```

Reload hosts in MCP Admin after editing.

## Sidecar tokens (required)

Store each host's `DHCP_SIDECAR_TOKEN` encrypted in MCP `/data/.env`:

```bash
# On icecream, inside the ssh-ops container or with SSH_OPS_ENV pointing at /data/.env
cd ~/clawlab/ssh-ops-mcp
python secrets_store.py set sidecar Services 'TOKEN_FROM_/etc/dhcp-sidecar/env'
python secrets_store.py set sidecar Nuc03 'TOKEN_FROM_/etc/dhcp-sidecar/env'
```

Fetch a token from a DHCP host:

```bash
ssh sshops@services.naboydciscolab.com \
  'sudo grep DHCP_SIDECAR_TOKEN= /etc/dhcp-sidecar/env | cut -d= -f2-'
```

## Deploy / upgrade MCP

After pulling this commit on icecream:

```bash
source ~/.clawlab/ssh-ops/ssh-env.sh
cd ~/clawlab/ssh-ops-mcp && CLAWLAB_MANAGE_MCP=1 bash podctl.sh --recreate
```

MCP Admin → Hosts → Reload hosts → test credentials.

## Example agent flow

```text
1. list_dhcp_hosts()
2. validate_dhcp_include("Services", "vlan100.conf", "<content>")
3. propose_change("Services", "dhcp_include", {"include_name": "vlan100.conf", "content": "..."}, intent="Add VLAN100 pool")
4. [Human approves in MCP Admin]
5. apply_change("chg-20260816-0001")
```

## Security

- Sidecar binds loopback only; MCP reaches it via SSH as `sshops`.
- Sidecar tokens are Fernet-encrypted in `/data/.env`, never in git or `hosts.yaml`.
- Four-eyes approval unchanged — agents cannot self-approve.
- Apply passes the queue `change_id` to the sidecar for backup/rollback linkage.
