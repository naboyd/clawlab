#!/usr/bin/env bash
# One-time bootstrap: allow icecream (or your Mac) to SSH as naboyd@Nuc03 for sudo installs.
#
# Run ON NUC03 as naboyd (console or existing login), paste the pubkey when prompted,
# or pass it as the first argument:
#
#   bash setup-nuc03-naboyd-key.sh 'ssh-ed25519 AAAA... comment'
#
# After this, from icecream:
#   ssh -i ~/.clawlab/ssh-ops/keys/nuc03-naboyd naboyd@192.168.128.15
set -Eeuo pipefail

PUBKEY="${1:-}"

if [[ -z "$PUBKEY" ]]; then
  echo "Paste the public key line from icecream (~/.clawlab/ssh-ops/keys/nuc03-naboyd.pub):"
  read -r PUBKEY
fi

[[ -n "$PUBKEY" ]] || { echo "error: empty pubkey" >&2; exit 1; }
[[ "$PUBKEY" == ssh-* ]] || { echo "error: expected ssh-ed25519 ... line" >&2; exit 1; }

install -d -m 700 "$HOME/.ssh"
AUTH="$HOME/.ssh/authorized_keys"
touch "$AUTH"
chmod 600 "$AUTH"
if grep -qxF "$PUBKEY" "$AUTH" 2>/dev/null; then
  echo "Key already present in $AUTH"
else
  echo "$PUBKEY" >> "$AUTH"
  echo "Added key to $AUTH"
fi
echo "OK: naboyd@$(hostname -f 2>/dev/null || hostname) ready for key auth"
