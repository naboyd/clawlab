# Cisco ThousandEyes MCP (OpenClaw)

ClawLab wires OpenClaw to Cisco's **hosted** ThousandEyes MCP — no local container
to build. The gateway calls `https://api.thousandeyes.com/mcp` with your org API token.

## Quick setup

1. **Create a token** in ThousandEyes:
   Account Settings → Users & Roles → your user → Edit → enable **API Access** →
   generate API token.

2. **On the lab host** (where OpenClaw runs):

```bash
cd ~/clawlab   # or ~/AI/clawlab
bash admin-access/configure-openclaw-thousandeyes-mcp.sh
systemctl --user restart openclaw-gateway
```

Or non-interactive:

```bash
THOUSANDEYES_API_TOKEN='your-token' bash admin-access/configure-openclaw-thousandeyes-mcp.sh
```

3. **Verify** in OpenClaw chat: ask "What ThousandEyes tests are configured?" or
   "Do I have any active alerts?"

## What gets configured

| Item | Location |
|------|----------|
| API token (secret) | `~/.clawlab/thousandeyes/env` (mode 600) |
| OpenClaw MCP entry | `~/.openclaw/openclaw.json` → `mcp.servers.thousandeyes` |
| Agent skill | `skills/thousandeyes/` → symlinked by `install-clawlab-skills.sh` |

OpenClaw JSON shape:

```json
"mcp": {
  "servers": {
    "thousandeyes": {
      "url": "https://api.thousandeyes.com/mcp",
      "transport": "streamable-http",
      "headers": {
        "Authorization": "Bearer <THOUSANDEYES_API_TOKEN>"
      }
    }
  }
}
```

## Auth model vs ssh-ops

| Server | Endpoint | Auth |
|--------|----------|------|
| ssh-ops | Lab `:8767/mcp` identity proxy | PAT `skops_…`, clawBind, or shared bearer |
| ThousandEyes | `api.thousandeyes.com/mcp` | ThousandEyes API token (org-wide) |

ThousandEyes does **not** go through the clawlab MCP identity proxy — OpenClaw talks
directly to Cisco's cloud MCP.

## Operations

```bash
# Rotate token (updates env file + openclaw.json)
bash admin-access/rotate-openclaw-thousandeyes-token.sh

# Remove from OpenClaw
bash admin-access/configure-openclaw-thousandeyes-mcp.sh --remove

# Re-link skills after git pull
bash admin-access/install-clawlab-skills.sh
```

## OAuth alternative

ThousandEyes also supports OAuth2 (browser flow). ClawLab uses **Bearer API tokens**
because the OpenClaw gateway runs headless on the lab host. For OAuth, use Cursor or
Claude Desktop with `mcp-remote` per [Cisco ThousandEyes MCP docs](https://docs.thousandeyes.com/).

## Security notes

- Never commit API tokens; `config-templates/thousandeyes.env.example` is a template only.
- Token grants ThousandEyes API access for your org — treat like a password; rotate on staff change.
- Instant-test tools can trigger live measurements; the agent skill asks for confirmation first.
- DefenseClaw still applies to OpenClaw tool calls; ssh-ops four-eyes does not apply to TE cloud APIs.

## Install wizard

`install-clawstack.sh` (interactive, without `--yes`) can prompt to run
`configure-openclaw-thousandeyes-mcp.sh` after optional extras.
