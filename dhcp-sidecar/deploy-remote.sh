#!/usr/bin/env bash
# Deploy dhcp-sidecar to Linux DHCP hosts via sshops (from icecream or any jump host).
set -Eeuo pipefail

REPO="${CLAWLAB_REPO:-$(cd "$(dirname "$0")/.." && pwd)}"
KEY="${SSHOPS_KEY:-$HOME/.clawlab/ssh-ops/keys/ssh-ops-mcp}"
SSH=(ssh -i "$KEY" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20)
RSYNC=(rsync -az -e "ssh -i $KEY -o BatchMode=yes -o StrictHostKeyChecking=accept-new")

say() { printf '>> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

[[ -f "$KEY" ]] || die "missing sshops key: $KEY"
[[ -d "$REPO/dhcp-sidecar" ]] || die "missing $REPO/dhcp-sidecar"

deploy_one() {
  local name="$1" target="$2"
  say "Deploying dhcp-sidecar → $name ($target)"
  "${SSH[@]}" "sshops@${target}" "mkdir -p /tmp/clawlab/dhcp-sidecar"
  "${RSYNC[@]}" "$REPO/dhcp-sidecar/" "sshops@${target}:/tmp/clawlab/dhcp-sidecar/"
  if ! "${SSH[@]}" "sshops@${target}" \
    "sudo -n CLAWLAB_REPO=/tmp/clawlab bash /tmp/clawlab/dhcp-sidecar/install-dhcp-sidecar.sh"; then
    say "FAIL: $name — sshops needs NOPASSWD for install script."
    say "  Run on icecream (enter sudo password when prompted):"
    say "    ssh -t naboyd@${target} 'sudo CLAWLAB_REPO=/tmp/clawlab bash /tmp/clawlab/dhcp-sidecar/install-dhcp-sidecar.sh'"
    say "  Or refresh sudoers via:"
    say "    bash $REPO/ssh-ops-mcp/scripts/setup-sshops-mcp-auth.sh --hosts ${name}"
    return 1
  fi
  "${SSH[@]}" "sshops@${target}" "curl -sf http://127.0.0.1:9080/health"
  say "OK: $name sidecar healthy on :9080"
}

HOSTS=("$@")
if [[ ${#HOSTS[@]} -eq 0 ]]; then
  HOSTS=(Services Nuc03)
fi

fail=0
for h in "${HOSTS[@]}"; do
  case "$h" in
    Services|services) deploy_one Services services.naboydciscolab.com || fail=1 ;;
    Nuc03|nuc03) deploy_one Nuc03 192.168.128.15 || fail=1 ;;
    *) die "unknown host inventory name: $h (use Services or Nuc03)" ;;
  esac
done
exit "$fail"
