# Contributing to clawlab

Thank you for contributing. This project is a **reference lab** for integrating
[OpenClaw](https://github.com/openclaw/openclaw), [DefenseClaw](https://github.com/cisco-ai-defense/defenseclaw),
and the ssh-ops MCP — not a supported Cisco product.

## Before you open a PR

1. **No secrets** — never commit `.env`, keys, certs, `hosts.yaml`, or real tokens.
2. **No personal lab data** — use `lab.example.com`, `192.168.1.x`, and synthetic
   command output in docs, samples, and training data.
3. **Run fast tests** when touching policy or MCP code:
   ```bash
   cd tests && ./policy-test.sh --no-agent
   ```

## Pull requests

- Keep changes focused; match existing shell/Python style in the touched directory.
- Update `docs/ARCHITECTURE.md` or `tests/README.md` when behavior or ports change.
- Regenerate diagram PNGs if you edit render scripts under `admin-access/render-*.py`.

## License

By contributing, you agree that your contributions are licensed under the
[Apache License 2.0](LICENSE).
