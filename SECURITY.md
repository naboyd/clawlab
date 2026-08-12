# Security

## Reporting a vulnerability

**Do not** open a public GitHub issue for security-sensitive reports.

Contact the maintainers through your organization's security channel, or email
the repository owners listed on the GitHub project page with:

- Description and impact
- Steps to reproduce
- Affected component (portal, MCP, install script, etc.)

## Scope notes

clawlab orchestrates high-privilege capabilities:

- SSH to network devices and Linux hosts
- Gated IOS-XE configuration changes
- LLM agents with MCP tool access

Treat deployments as **lab or isolated environments**. Do not expose admin
ports (`8443`, `8766`, `18789`) to untrusted networks without additional
hardening.

## Secrets

Runtime secrets belong on the host (`~/.openclaw`, `~/.defenseclaw`,
`~/.claw-auth`, ssh-ops `data/.env`). See `config-templates/*.example` for
sanitized templates.
