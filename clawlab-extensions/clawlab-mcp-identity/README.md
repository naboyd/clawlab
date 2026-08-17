# Clawlab MCP identity extension

Injects `X-Claw-Mcp-Bind` on outbound MCP HTTP calls so the
[ssh-ops MCP identity proxy](../../ssh-ops-mcp/mcp_identity_proxy.py) can attach
verified `X-Auth-User` / `X-Auth-Role` headers.

## Install

```bash
bash admin-access/configure-openclaw-mcp-identity.sh
systemctl --user restart openclaw-gateway
```

## Flow

1. User signs into the portal hub (claw-auth).
2. Hub OpenClaw link includes `clawBind=<short-lived token>`.
3. This extension reads `clawBind` from the Control UI URL (or `CLAW_MCP_BIND` env).
4. OpenClaw MCP calls go to `http://127.0.0.1:8767/mcp` (identity proxy).
5. Proxy validates bind token → forwards user/role to ssh-ops MCP.
6. RBAC blocks sensitive reads (e.g. full `show running-config`) for non-admin roles.

**Alternative:** PAT in `openclaw.json` via `admin-access/set-openclaw-mcp-pat.sh`
(useful for bookmarked `/openclaw/chat` URLs without `clawBind`).

## Operator testing

Create a non-admin user:

```bash
python claw-auth/manage.py create-user alice --role operator
```

Alice can run filtered shows but not full `show running-config` or `download_file`.
