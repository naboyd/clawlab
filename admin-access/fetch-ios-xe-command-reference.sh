#!/usr/bin/env bash
# Download Cisco IOS-XE 17.17 Catalyst 9200 command reference PDF into docs/reference/.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${REPO}/docs/reference/ios-xe-17.17-c9200-command-reference.pdf"
URL="https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9200/software/release/17-17/command_reference/b_1717_9200_cr.pdf"
mkdir -p "${REPO}/docs/reference"
curl -fsSL -o "$OUT" "$URL"
echo "Saved $(du -h "$OUT" | awk '{print $1}') -> $OUT"
echo "Regenerate policy groups: python3 admin-access/sync-ios-xe-policy.py"
