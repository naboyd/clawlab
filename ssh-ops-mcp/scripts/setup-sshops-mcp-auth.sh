#!/usr/bin/env bash
#
# setup-sshops-mcp-auth.sh — dedicated ssh-ops automation user + Ed25519 key
#
# Run on icecream (or any host that can SSH as your admin user to the targets):
#
#   cd ~/clawlab/ssh-ops-mcp
#   bash scripts/setup-sshops-mcp-auth.sh
#
# What it does:
#   1. Creates ~/.clawlab/ssh-ops/keys/ssh-ops-mcp (Ed25519) + known_hosts
#   2. On each Linux host: user "sshops", authorized_keys, passwordless sudo
#      for systemctl + apt (scoped in /etc/sudoers.d/sshops-mcp)
#   3. Updates ~/.clawlab/ssh-ops/data/hosts.yaml (username + key_path)
#   4. Removes stored login/sudo secrets for those hosts (key auth + NOPASSWD sudo)
#
# Options:
#   --dry-run          Print actions only
#   --hosts LIST       Comma-separated inventory names only (e.g. Services,Nuc03,splunk)
#   --skip-secrets     Do not edit encrypted .env secrets
#   --skip-hosts-yaml  Do not patch hosts.yaml
#   --keep-sudo-secrets  Leave encrypted sudo passwords in .env
#
set -euo pipefail

SSHOPS_USER="${SSHOPS_USER:-sshops}"
SSHOPS_GROUP="${SSHOPS_GROUP:-sshops}"
BOOTSTRAP_USER="${SSHOPS_BOOTSTRAP_USER:-${USER:-naboyd}}"
KEY_DIR="${SSHOPS_KEY_DIR:-$HOME/.clawlab/ssh-ops/keys}"
KEY_FILE="$KEY_DIR/ssh-ops-mcp"
KNOWN_HOSTS="$KEY_DIR/known_hosts"
DATA_DIR="${SSH_OPS_DATA:-$HOME/.clawlab/ssh-ops/data}"
HOSTS_YAML="${SSH_OPS_CONFIG:-$DATA_DIR/hosts.yaml}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Inventory names (must match keys in hosts.yaml) — order preserved.
HOST_INVENTORY=(icecream Services Nuc03 splunk)

host_target() {
  case "$1" in
    icecream) echo "icecream.naboydciscolab.com" ;;
    Services) echo "services.naboydciscolab.com" ;;
    Nuc03) echo "192.168.128.15" ;;
    splunk) echo "splunk.naboydciscolab.com" ;;
    *) return 1 ;;
  esac
}

DRY_RUN=0
SKIP_SECRETS=0
SKIP_HOSTS_YAML=0
KEEP_SUDO_SECRETS=0
ONLY_HOSTS=()

usage() {
  sed -n '3,22p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --hosts)
      [[ $# -ge 2 ]] || { echo "error: --hosts requires a comma-separated list" >&2; exit 1; }
      IFS=',' read -r -a ONLY_HOSTS <<< "$2"
      shift 2
      continue
      ;;
    --skip-secrets) SKIP_SECRETS=1 ;;
    --skip-hosts-yaml) SKIP_HOSTS_YAML=1 ;;
    --keep-sudo-secrets) KEEP_SUDO_SECRETS=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 1 ;;
  esac
  shift
done

host_selected() {
  local inv="$1"
  if [[ ${#ONLY_HOSTS[@]} -eq 0 ]]; then
    return 0
  fi
  local pick
  for pick in "${ONLY_HOSTS[@]}"; do
    if [[ "$pick" == "$inv" ]]; then
      return 0
    fi
  done
  return 1
}

selected_hosts_csv() {
  local inv out=""
  for inv in "${HOST_INVENTORY[@]}"; do
    host_selected "$inv" || continue
    out+="${out:+,}${inv}"
  done
  printf '%s' "$out"
}

say() { printf '>> %s\n' "$*"; }
run() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    printf '[dry-run]'; printf ' %q' "$@"; printf '\n'
  else
    "$@"
  fi
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "error: required command not found: $1" >&2
    exit 1
  }
}

is_local_target() {
  local target="$1"
  local short
  short="$(hostname -s 2>/dev/null || hostname)"
  [[ "$target" == "127.0.0.1" || "$target" == "localhost" ]] && return 0
  [[ "$target" == "$(hostname -f 2>/dev/null || true)" ]] && return 0
  [[ "$target" == "$(hostname 2>/dev/null || true)" ]] && return 0
  [[ "$target" == "${short}"* ]] && return 0
  return 1
}

remote_exec() {
  # remote_exec <bootstrap_user> <host> <script_body>
  local user="$1" host="$2" body="$3"
  if is_local_target "$host"; then
    if [[ "$DRY_RUN" -eq 1 ]]; then
      printf '[dry-run] local sudo bash <<SETUP\n%s\nSETUP\n' "$body"
      return 0
    fi
    printf '%s\n' "$body" | sudo bash
  else
    if [[ "$DRY_RUN" -eq 1 ]]; then
      printf '[dry-run] ssh -t %s@%s sudo bash -s <<SETUP\n%s\nSETUP\n' "$user" "$host" "$body"
      return 0
    fi
    # -t required so remote sudo can prompt for naboyd password during bootstrap.
    ssh -t -o ConnectTimeout=15 "${user}@${host}" 'sudo bash -s' <<REMOTE_SCRIPT
${body}
REMOTE_SCRIPT
  fi
}

generate_key() {
  need_cmd ssh-keygen
  run mkdir -p "$KEY_DIR"
  run chmod 700 "$KEY_DIR"
  if [[ -f "$KEY_FILE" ]]; then
    say "Using existing key $KEY_FILE"
  else
    say "Generating Ed25519 key $KEY_FILE"
    run ssh-keygen -t ed25519 -f "$KEY_FILE" -C "ssh-ops-mcp@$(hostname -s)" -N ""
  fi
  run chmod 600 "$KEY_FILE"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    return 0
  fi
  [[ -f "${KEY_FILE}.pub" ]] || {
    echo "error: missing ${KEY_FILE}.pub" >&2
    exit 1
  }
}

scan_known_hosts() {
  need_cmd ssh-keyscan
  say "Updating $KNOWN_HOSTS"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    for inv in "${HOST_INVENTORY[@]}"; do
      printf '[dry-run] ssh-keyscan -H %s >> %s\n' "$(host_target "$inv")" "$KNOWN_HOSTS"
    done
    return 0
  fi
  : >"$KNOWN_HOSTS"
  run chmod 600 "$KNOWN_HOSTS"
  local inv host
  for inv in "${HOST_INVENTORY[@]}"; do
    host="$(host_target "$inv")" || continue
    ssh-keyscan -H "$host" 2>/dev/null >>"$KNOWN_HOSTS" || {
      echo "warning: ssh-keyscan failed for $host (host may be down)" >&2
    }
  done
}

install_on_host() {
  local inv_name="$1"
  local target="$2"
  local pubkey
  if [[ "$DRY_RUN" -eq 1 ]]; then
    pubkey="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5-dry-run ssh-ops-mcp@dry-run"
  else
    pubkey="$(cat "${KEY_FILE}.pub")"
  fi

  say "Configuring $inv_name ($target) → user $SSHOPS_USER"

  local body
  body="$(cat <<SETUP
set -euo pipefail
SSHOPS_USER=$(printf '%q' "$SSHOPS_USER")
SSHOPS_GROUP=$(printf '%q' "$SSHOPS_GROUP")
PUBKEY=$(printf '%q' "$pubkey")

SYSTEMCTL=""
for c in /usr/bin/systemctl /bin/systemctl; do
  [[ -x "\$c" ]] && SYSTEMCTL="\$c" && break
done
[[ -n "\$SYSTEMCTL" ]] || { echo "systemctl not found"; exit 1; }

APT_GET=""
APT=""
for c in /usr/bin/apt-get /bin/apt-get; do
  [[ -x "\$c" ]] && APT_GET="\$c" && break
done
for c in /usr/bin/apt /bin/apt; do
  [[ -x "\$c" ]] && APT="\$c" && break
done

if ! id "\${SSHOPS_USER}" >/dev/null 2>&1; then
  useradd -m -s /bin/bash -c "ssh-ops MCP automation" "\${SSHOPS_USER}"
fi
install -d -m 700 -o "\${SSHOPS_USER}" -g "\${SSHOPS_GROUP}" "/home/\${SSHOPS_USER}/.ssh"
AUTH="/home/\${SSHOPS_USER}/.ssh/authorized_keys"
touch "\${AUTH}"
chown "\${SSHOPS_USER}:\${SSHOPS_GROUP}" "\${AUTH}"
chmod 600 "\${AUTH}"
grep -qxF "\${PUBKEY}" "\${AUTH}" || echo "\${PUBKEY}" >> "\${AUTH}"

SUDOERS="/etc/sudoers.d/sshops-mcp"
TMP="\${SUDOERS}.tmp.\$\$"
{
  cat <<SUDOERS_INNER
# Managed by clawlab setup-sshops-mcp-auth.sh - do not edit by hand.
# Inventory host: ${inv_name}
Cmnd_Alias SSHOPS_SYSTEMCTL = \\
  \${SYSTEMCTL} restart *, \\
  \${SYSTEMCTL} start *, \\
  \${SYSTEMCTL} stop *, \\
  \${SYSTEMCTL} reload *, \\
  \${SYSTEMCTL} try-restart *, \\
  \${SYSTEMCTL} status *, \\
  \${SYSTEMCTL} is-active *, \\
  \${SYSTEMCTL} is-enabled *, \\
  \${SYSTEMCTL} show *, \\
  \${SYSTEMCTL} daemon-reload, \\
  \${SYSTEMCTL} list-units *, \\
  \${SYSTEMCTL} list-unit-files *
SUDOERS_INNER
  if [[ -n "\${APT_GET}" ]]; then
    cat <<SUDOERS_INNER
Cmnd_Alias SSHOPS_APT_GET = \\
  \${APT_GET} update, \\
  \${APT_GET} -y update, \\
  \${APT_GET} -y upgrade, \\
  \${APT_GET} -y dist-upgrade, \\
  \${APT_GET} -y autoremove, \\
  \${APT_GET} -y install *, \\
  \${APT_GET} -y remove *, \\
  \${APT_GET} -y purge *
SUDOERS_INNER
  fi
  if [[ -n "\${APT}" ]]; then
    cat <<SUDOERS_INNER
Cmnd_Alias SSHOPS_APT = \\
  \${APT} update, \\
  \${APT} -y update, \\
  \${APT} -y upgrade, \\
  \${APT} -y install *, \\
  \${APT} -y remove *
SUDOERS_INNER
  fi
  SUDO_PARTS="SSHOPS_SYSTEMCTL"
  if [[ -n "\${APT_GET}" ]]; then
    SUDO_PARTS="\${SUDO_PARTS}, SSHOPS_APT_GET"
  fi
  if [[ -n "\${APT}" ]]; then
    SUDO_PARTS="\${SUDO_PARTS}, SSHOPS_APT"
  fi
  printf '%s ALL=(root) NOPASSWD: %s\n' "\${SSHOPS_USER}" "\${SUDO_PARTS}"
} > "\${TMP}"
chmod 440 "\${TMP}"
visudo -cf "\${TMP}"
install -o root -g root -m 440 "\${TMP}" "\${SUDOERS}"
rm -f "\${TMP}"
echo "OK: \${SSHOPS_USER} on \$(hostname -f 2>/dev/null || hostname)"
SETUP
)"

  remote_exec "$BOOTSTRAP_USER" "$target" "$body"
}

verify_key_login() {
  local inv_name="$1"
  local target="$2"
  say "Verifying key login to $inv_name ($target)"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    printf '[dry-run] ssh -i %s -o BatchMode=yes %s@%s "sudo -n %s is-system-running || true"\n' \
      "$KEY_FILE" "$SSHOPS_USER" "$target" "/usr/bin/systemctl"
    return 0
  fi
  local systemctl="/usr/bin/systemctl"
  ssh -i "$KEY_FILE" -o BatchMode=yes -o ConnectTimeout=15 \
    -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$KNOWN_HOSTS" \
    "${SSHOPS_USER}@${target}" "sudo -n ${systemctl} is-system-running >/dev/null 2>&1 || sudo -n ${systemctl} status --no-pager -n 0 >/dev/null"
  say "  ✓ $inv_name"
}

patch_hosts_yaml() {
  [[ "$SKIP_HOSTS_YAML" -eq 1 ]] && return 0
  [[ -f "$HOSTS_YAML" ]] || {
    echo "error: hosts.yaml not found at $HOSTS_YAML" >&2
    exit 1
  }
  say "Patching $HOSTS_YAML (username=$SSHOPS_USER, key_path=/root/.ssh/ssh-ops-mcp)"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    printf '[dry-run] python patch hosts.yaml for: %s\n' "${HOST_INVENTORY[*]}"
    return 0
  fi
  need_cmd python3
  HOSTS_YAML="$HOSTS_YAML" SSHOPS_USER="$SSHOPS_USER" SSHOPS_TARGETS="$(selected_hosts_csv)" python3 <<'PY'
import os
from pathlib import Path

try:
    import yaml
except ImportError as exc:
    raise SystemExit("PyYAML required: pip install pyyaml") from exc

path = Path(os.environ["HOSTS_YAML"])
targets = [t.strip() for t in os.environ["SSHOPS_TARGETS"].split(",") if t.strip()]
user = os.environ["SSHOPS_USER"]
cfg = yaml.safe_load(path.read_text()) or {}
hosts = cfg.setdefault("hosts", {})
for name in targets:
    if name not in hosts:
        print(f"warning: {name} not in hosts.yaml — skipping")
        continue
    entry = hosts[name]
    entry["username"] = user
    entry["key_path"] = "/root/.ssh/ssh-ops-mcp"
    entry.setdefault("platform", "linux")
path.write_text(yaml.dump(cfg, default_flow_style=False, sort_keys=False))
print(f"updated {path} for: {', '.join(targets)}")
PY
}

clear_secrets() {
  [[ "$SKIP_SECRETS" -eq 1 ]] && return 0
  local env_file="$DATA_DIR/.env"
  local keyfile="$DATA_DIR/master.key"
  [[ -f "$env_file" && -f "$keyfile" ]] || {
    say "No encrypted secrets at $DATA_DIR — skipping secret cleanup"
    return 0
  }
  say "Removing login secrets (and sudo if not --keep-sudo-secrets) from $env_file"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    printf '[dry-run] clear login/sudo secrets for: %s\n' "${HOST_INVENTORY[*]}"
    return 0
  fi
  KEEP_SUDO="$KEEP_SUDO_SECRETS" DATA_DIR="$DATA_DIR" REPO_DIR="$REPO_DIR" SSHOPS_TARGETS="$(selected_hosts_csv)" python3 <<'PY'
import os
import sys
from pathlib import Path

repo = Path(os.environ["REPO_DIR"])
sys.path.insert(0, str(repo))

os.environ.setdefault("SSH_OPS_ENV", str(Path(os.environ["DATA_DIR"]) / ".env"))
os.environ.setdefault("SSH_OPS_KEYFILE", str(Path(os.environ["DATA_DIR"]) / "master.key"))

import secrets_store  # noqa: E402

targets = [t.strip() for t in os.environ["SSHOPS_TARGETS"].split(",") if t.strip()]
keep_sudo = os.environ.get("KEEP_SUDO", "0") == "1"
for host in targets:
    for kind in ("login", "sudo"):
        if kind == "sudo" and keep_sudo:
            continue
        try:
            secrets_store.delete_secret(host, kind)
            print(f"deleted {host} {kind} secret")
        except Exception:
            pass
PY
}

write_env_hint() {
  local hint="$HOME/.clawlab/ssh-ops/ssh-env.sh"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    printf '[dry-run] write %s\n' "$hint"
    return 0
  fi
  cat >"$hint" <<EOF
# Source before podctl so MCP mounts the dedicated automation key (not all of ~/.ssh).
export SSH_OPS_SSH="$KEY_DIR"
EOF
  chmod 600 "$hint"
  say "Wrote $hint — use: source $hint"
}

main() {
  need_cmd ssh
  [[ -f "$HOSTS_YAML" ]] || echo "warning: $HOSTS_YAML missing; use --skip-hosts-yaml or create it first" >&2

  say "Bootstrap SSH user: $BOOTSTRAP_USER"
  say "Automation user:    $SSHOPS_USER"
  say "Key directory:      $KEY_DIR"

  generate_key
  scan_known_hosts

  local inv target
  for inv in "${HOST_INVENTORY[@]}"; do
    host_selected "$inv" || continue
    target="$(host_target "$inv")" || continue
    install_on_host "$inv" "$target"
  done

  for inv in "${HOST_INVENTORY[@]}"; do
    host_selected "$inv" || continue
    target="$(host_target "$inv")" || continue
    verify_key_login "$inv" "$target"
  done

  patch_hosts_yaml
  clear_secrets
  write_env_hint

  cat <<EOF

Done.

Next on icecream:
  1. source ~/.clawlab/ssh-ops/ssh-env.sh
  2. cd ~/clawlab/ssh-ops-mcp && CLAWLAB_MANAGE_MCP=1 bash podctl.sh --recreate
  3. MCP Admin → Hosts → Reload hosts into MCP
  4. Test credentials for each host (should use key, no login password)

Container key path: /root/.ssh/ssh-ops-mcp
Host key file:      $KEY_FILE
Known hosts:        $KNOWN_HOSTS
EOF
}

main "$@"
