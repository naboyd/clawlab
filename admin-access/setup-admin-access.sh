#!/usr/bin/env bash
# setup-admin-access.sh — expose the OpenClaw Control UI on the LAN with HTTPS
# and Linux-user (PAM) authentication via an nginx reverse proxy.
#     sudo ./setup-admin-access.sh
set -Eeuo pipefail
if [[ "${EUID}" -ne 0 ]]; then echo "Run as root: sudo $0" >&2; exit 1; fi
LAN_IP="${LAN_IP:-192.168.128.93}"
PORT="${PORT:-8443}"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
CERT_DIR=/etc/nginx/ssl
echo "==> Installing nginx + PAM auth module"
export DEBIAN_FRONTEND=noninteractive
apt-get update -o Acquire::Retries=3
apt-get install -y nginx libnginx-mod-http-auth-pam openssl
echo "==> Generating self-signed cert"
install -d -m 0755 "$CERT_DIR"
if [[ ! -f "$CERT_DIR/openclaw-admin.crt" ]]; then
  openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
    -keyout "$CERT_DIR/openclaw-admin.key" \
    -out    "$CERT_DIR/openclaw-admin.crt" \
    -subj   "/CN=icecream" \
    -addext "subjectAltName=DNS:icecream,IP:${LAN_IP}"
  chmod 600 "$CERT_DIR/openclaw-admin.key"
fi
echo "==> Deploying PAM service"
install -m 0644 "${SRC_DIR}/pam-openclaw-admin" /etc/pam.d/openclaw-admin
echo "==> Deploying nginx site"
install -m 0644 "${SRC_DIR}/openclaw-admin.nginx.conf" /etc/nginx/sites-available/openclaw-admin.conf
ln -sf /etc/nginx/sites-available/openclaw-admin.conf /etc/nginx/sites-enabled/openclaw-admin.conf
echo "==> Granting nginx access to verify Linux passwords (shadow group)"
usermod -aG shadow www-data
echo "==> Testing + reloading nginx"
nginx -t
systemctl enable --now nginx
systemctl reload nginx
cat <<EOF

Done. Control UI proxy: https://${LAN_IP}:${PORT}/
Log in with any Linux account on icecream (self-signed cert warning expected).

NEXT (after 'openclaw onboard'):
  1. Merge openclaw.trusted-proxy.json5 into ~/.openclaw/openclaw.json
  2. Restart the gateway
  3. First visit: approve the device if prompted (openclaw devices list/approve)

Firewall (if ufw active):
  sudo ufw allow from 192.168.128.0/24 to any port ${PORT} proto tcp
EOF
