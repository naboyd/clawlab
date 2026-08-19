# Key and token rotation (ClawLab)

ClawLab uses several credentials. Rotate them on a schedule, after staff changes, or whenever a value may have been exposed (logs, chat, screenshots).

| Credential | Prefix / type | Used by | Where stored |
|------------|---------------|---------|--------------|
| **MCP personal access token (PAT)** | `skops_…` | Cursor, Claude Desktop, bookmarked OpenClaw | `~/.openclaw/openclaw.json` (optional) |
| **MCP shared bearer** | opaque | Legacy / internal MCP clients on `:8766` | `~/.ssh-ops-mcp/secrets.json` |
| **OpenClaw gateway token** | opaque | Control UI `#token=` fragment | `~/.openclaw/.env`, systemd drop-ins |
| **Portal session** | cookie | Hub, MCP Admin, DefenseClaw | Server-side in `~/.claw-auth/users.db` |
| **clawBind** | short-lived | OpenClaw opened from hub | Not stored — issued per hub link |

**Recommended OpenClaw path:** open chat from the portal hub (**Open OpenClaw ↗**). That uses `clawBind` on the identity proxy (`:8767`) — no PAT on disk.

Use PAT rotation only when you bookmark OpenClaw URLs or connect external MCP clients.

---

## 1. Rotate OpenClaw MCP PAT (`skops_…`) — automated

Issues a new PAT, revokes prior tokens with the same label, writes `~/.openclaw/openclaw.json`, and restarts the gateway.

```bash
cd ~/clawlab
bash admin-access/rotate-openclaw-mcp-pat.sh
```

Options:

```bash
# Another user (superadmin on shared host)
bash admin-access/rotate-openclaw-mcp-pat.sh --user alice

# Custom label in hub token list
bash admin-access/rotate-openclaw-mcp-pat.sh --label openclaw-gateway --ttl-days 90

# Issue only (manual openclaw.json edit)
bash admin-access/rotate-openclaw-mcp-pat.sh --no-apply

# Write config but restart gateway yourself
bash admin-access/rotate-openclaw-mcp-pat.sh --no-restart
systemctl --user restart openclaw-gateway
```

Verify:

```bash
bash tests/mcp-ping.sh
```

### Portal hub button

On a co-located lab host (OpenClaw on the same machine as claw-auth):

1. Hub → **MCP tokens**
2. **Create token** — enable **Install in OpenClaw on this server** (when `~/.openclaw/openclaw.json` exists)
3. Or use **Rotate OpenClaw PAT** — one click: revoke old `openclaw-gateway` label, issue new, apply, restart

External Cursor clients still need the token copied once from the “copy now” banner.

### Manual PAT apply (existing token)

If you already created a PAT in the hub:

```bash
OPENCLAW_MCP_PAT='skops_…' bash admin-access/set-openclaw-mcp-pat.sh
systemctl --user restart openclaw-gateway
```

---

## 2. Revoke a leaked or unused PAT

**Hub UI:** MCP tokens → **revoke** on the row.

**API:**

```bash
curl -X DELETE -b "claw_session=…" "https://<host>:8443/mcp/tokens/<id>"
```

After revoke, rotate or update any client still using the old value (`openclaw.json`, Cursor config).

---

## 3. Rotate MCP shared bearer (`:8766` upstream)

Used by the MCP server container itself — **not** what Cursor or OpenClaw should send. Clients must use the identity proxy on **`:8767`**.

**MCP Admin GUI:** `https://<host>:8443/ssh-ops/` → token page → **Rotate token**.

Or on the host:

```bash
cd ~/clawlab/ssh-ops-mcp
podman exec ssh-ops-mcp python -c "import secrets_store; print(secrets_store.rotate_mcp_token())"
```

Then re-sync gateway auth (preserves `skops_` PATs if present):

```bash
bash admin-access/sync-openclaw-gateway-mcp-auth.sh
bash admin-access/configure-portal-mcp-auth.sh   # if nginx/proxy env changed
```

---

## 4. Rotate OpenClaw gateway token

Gateway token protects the Control UI and WebSocket — separate from MCP PAT.

```bash
bash admin-access/apply-token-portal.py   # or your site’s token apply script
systemctl --user restart openclaw-gateway
```

Re-copy the hub **Open OpenClaw ↗** link if bookmarks used `#token=…`.

---

## 5. Rotate portal passwords

Hub → user admin (superadmin) or CLI against `~/.claw-auth/users.db`.

Rotating a password does **not** revoke MCP PATs. Revoke PATs separately if the account was compromised.

---

## Rotation checklist (production)

1. **OpenClaw from hub** — confirm `clawBind` still works (no PAT needed).
2. **OpenClaw bookmark / PAT** — `rotate-openclaw-mcp-pat.sh` or hub **Rotate OpenClaw PAT**.
3. **Cursor / external MCP** — new PAT on `:8767/mcp`; revoke old PAT in hub.
4. **Shared MCP bearer** — rotate in ssh-ops GUI if exposed; run `sync-openclaw-gateway-mcp-auth.sh`.
5. **Run** `bash tests/mcp-ping.sh` — all steps green, including `propose_change` identity.
6. **Avoid** `install/local-full-ctl.sh` on Linux lab portals — use `podctl.sh --recreate` and targeted restarts instead.

---

## Environment variables

| Variable | Purpose |
|----------|---------|
| `CLAW_AUTH_DB` | SQLite user/PAT store (default `~/.claw-auth/users.db`) |
| `OPENCLAW_HOME` | OpenClaw state dir (default `~/.openclaw`) |
| `OPENCLAW_SKIP_GATEWAY_RESTART` | Set to `1` to skip gateway restart in scripts |
| `SSH_OPS_MCP_GATEWAY_URL` | Override MCP URL written to `openclaw.json` |

---

## Related docs

- [USER-GUIDE.md](USER-GUIDE.md) — day-to-day usage and troubleshooting
- [ARCHITECTURE.md](ARCHITECTURE.md) — `:8767` identity proxy vs `:8766` upstream
- [claw-auth/README.md](../claw-auth/README.md) — PAT API
- [ssh-ops-mcp/README.md](../ssh-ops-mcp/README.md) — MCP server and client setup
