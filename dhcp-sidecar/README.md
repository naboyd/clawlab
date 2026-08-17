# dhcp-sidecar — Phase A

Local **ISC DHCP include-file** sidecar for lab DHCP servers (Services, Nuc03, …).
Runs on the host with narrow scope: only `/etc/dhcp/dhcpd.d/*.conf`, `dhcpd -t`, and
`systemctl reload isc-dhcp-server`.

## Features (Phase A)

- **JSON API** for validate / apply / rollback (Bearer token)
- **Local Web UI** on `127.0.0.1:9080` (token login → session cookie)
- **`dhcpd -t`** before every apply; backup + manifest before write
- **Audit log** at `/var/lib/dhcp-sidecar/audit.log`

Not included yet: icecream `isc-dhcp` MCP, four-eyes approval gate, mTLS.

## Install (on DHCP server, as root)

```bash
# From a checkout on the host, or after git pull:
sudo CLAWLAB_REPO=/home/naboyd/clawlab bash /home/naboyd/clawlab/dhcp-sidecar/install-dhcp-sidecar.sh
```

Creates:

| Path | Purpose |
|------|---------|
| `/opt/clawlab/dhcp-sidecar/` | App + venv |
| `/etc/dhcp-sidecar/env` | `DHCP_SIDECAR_TOKEN` (Bearer) |
| `/var/lib/dhcp-sidecar/` | Staging, backups, audit |
| `/etc/systemd/system/dhcp-sidecar.service` | systemd unit |

Ensure main `dhcpd.conf` includes the drop-in directory, e.g.:

```conf
include "/etc/dhcp/dhcpd.d/*.conf";
```

## API

All `/api/*` routes require:

```http
Authorization: Bearer <DHCP_SIDECAR_TOKEN>
```

| Method | Path | Body |
|--------|------|------|
| GET | `/health` | — |
| GET | `/api/includes` | — |
| GET | `/api/includes/{name}` | — |
| POST | `/api/includes/{name}/validate` | `{"content":"..."}` |
| POST | `/api/includes/{name}/apply` | `{"change_id":"chg-…","content":"..."}` |
| POST | `/api/rollback/{change_id}` | optional `{"actor":"…"}` |

### Example (from icecream via SSH tunnel)

```bash
# On Mac: ssh -L 9080:127.0.0.1:9080 naboyd@services...
TOKEN="$(sudo grep DHCP_SIDECAR_TOKEN= /etc/dhcp-sidecar/env | cut -d= -f2-)"

curl -s http://127.0.0.1:9080/health | jq .

curl -s -X POST http://127.0.0.1:9080/api/includes/vlan100.conf/validate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content":"subnet 10.100.0.0 netmask 255.255.255.0 {\n}\n"}' | jq .

curl -s -X POST http://127.0.0.1:9080/api/includes/vlan100.conf/apply \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"change_id":"chg-test-001","content":"subnet 10.100.0.0 netmask 255.255.255.0 {\n  range 10.100.0.50 10.100.0.200;\n}\n"}' | jq .

curl -s -X POST http://127.0.0.1:9080/api/rollback/chg-test-001 \
  -H "Authorization: Bearer $TOKEN" | jq .
```

## Web UI

Open `http://127.0.0.1:9080/` on the server (or via SSH tunnel). Paste the API token once.

## Security notes

- Binds **127.0.0.1** by default — reach via SSH tunnel or internal orchestrator only.
- Include names must match `[a-zA-Z0-9][a-zA-Z0-9._-]*.conf` — no path traversal.
- No shell execution; only `dhcpd -t` and `systemctl reload isc-dhcp-server`.
- Phase B will add icecream approval verification before apply.

## Tests

```bash
cd dhcp-sidecar
python3 -m unittest discover -s tests -v
```

## Roadmap

- **Phase B:** Web UI polish + audit viewer + install on second host
- **Phase C:** `isc-dhcp-mcp` on icecream + change-queue integration
- **Phase D:** Failover ordering (primary → secondary)
