#!/usr/bin/env bash
# issue-cert.sh — obtain Let's Encrypt cert via lego + GoDaddy DNS-01
set -Eeuo pipefail

DOMAIN="${DOMAIN:-icecream.naboydciscolab.com}"
EMAIL="${LE_EMAIL:-boydn@me.com}"
LEGO_PATH="${LEGO_PATH:-$HOME/mcp/acme/lego}"
ENV_FILE="${GODADDY_ENV:-$HOME/mcp/acme/godaddy.env}"
LEGO_BIN="${LEGO_BIN:-$HOME/go/bin/lego}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE — copy acme/godaddy.env.example and fill in API keys." >&2
  exit 1
fi

if [[ ! -x "$LEGO_BIN" ]]; then
  echo "lego not found at $LEGO_BIN" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$ENV_FILE"

CERT="$LEGO_PATH/certificates/${DOMAIN}.crt"
KEY="$LEGO_PATH/certificates/${DOMAIN}.key"

if [[ -f "$CERT" && -f "$KEY" ]]; then
  echo "Certificate already exists: $CERT"
  exit 0
fi

echo "==> Requesting certificate for $DOMAIN (DNS-01 via GoDaddy)"
mkdir -p "$LEGO_PATH"
"$LEGO_BIN" --accept-tos --email "$EMAIL" --dns godaddy \
  --dns.propagation-wait=120s --domains "$DOMAIN" --path "$LEGO_PATH" run

echo "==> Certificate written to $CERT"
