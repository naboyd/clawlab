# Cisco IOS-XE command reference (local copy)

Official source used to derive `config-templates/ios-xe-policy.yaml` allow_groups:

| File | Source |
|------|--------|
| `ios-xe-17.17-c9200-command-reference.pdf` | [Catalyst 9200 IOS-XE 17.17 Command Reference](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9200/software/release/17-17/command_reference/b_1717_9200_cr.pdf) |

Chapter-to-group mapping: `docs/ios-xe-command-reference-index.yaml` (60 granular groups in 11 categories).

Re-download and regenerate policy (maintainer fetch script is in local `_archive/`):

```bash
curl -fsSL -o docs/reference/ios-xe-17.17-c9200-command-reference.pdf \
  'https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9200/software/release/17-17/command_reference/b_1717_9200_cr.pdf'
python3 admin-access/sync-ios-xe-policy.py
```
