#!/usr/bin/env bash
# ThousandEyes hosted MCP connectivity test (stateless SSE — no Mcp-Session-Id).
#
#   bash tests/thousandeyes-mcp-ping.sh
#   THOUSANDEYES_API_TOKEN=… bash tests/thousandeyes-mcp-ping.sh
set -Eeuo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
TE_ENV="${CLAWLAB_THOUSANDEYES_ENV:-$HOME/.clawlab/thousandeyes/env}"
MCP_URL="${THOUSANDEYES_MCP_URL:-https://api.thousandeyes.com/mcp}"

step() { printf '\n== %s ==\n' "$1"; }
ok() { printf '  OK: %s\n' "$1"; }
fail() { printf '  FAIL: %s\n' "$1"; exit 1; }

token="${THOUSANDEYES_API_TOKEN:-}"
if [[ -z "$token" && -f "$TE_ENV" ]]; then
  # shellcheck disable=SC1090
  set -a; source "$TE_ENV"; set +a
  token="${THOUSANDEYES_API_TOKEN:-}"
fi
[[ -n "$token" ]] || fail "no token — set THOUSANDEYES_API_TOKEN or run configure-openclaw-thousandeyes-mcp.sh"
token="${token#Bearer }"
AUTH="Bearer $token"

parse_sse() {
  python3 - "$1" <<'PY'
import json, sys, re
from pathlib import Path
raw = Path(sys.argv[1]).read_text()
for part in re.findall(r'^data: (.+)$', raw, re.M):
    try:
        d = json.loads(part)
    except json.JSONDecodeError:
        continue
    if "result" in d or "error" in d:
        print(json.dumps(d))
        raise SystemExit(0)
try:
    print(json.dumps(json.loads(raw)))
except json.JSONDecodeError:
    raise SystemExit(1)
PY
}

hdr=(
  -H "Authorization: $AUTH"
  -H 'Content-Type: application/json'
  -H 'Accept: application/json, text/event-stream'
)

step "1) Config"
ok "MCP_URL=$MCP_URL"
ok "token from ${TE_ENV#$HOME/} or env"

step "2) initialize"
raw="$(mktemp)"
curl -sS -m20 -o "$raw" -X POST "$MCP_URL" "${hdr[@]}" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"clawlab-te-ping","version":"1"}}}' \
  || fail "initialize curl failed"
init="$(parse_sse "$raw" || true)"
[[ -n "$init" ]] || fail "initialize parse failed"
python3 -c "import json,sys; d=json.load(sys.stdin); si=d.get('result',{}).get('serverInfo',{}); print('  OK: server', si.get('name'), si.get('version'))" <<<"$init"

curl -sS -m10 -o /dev/null -X POST "$MCP_URL" "${hdr[@]}" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}' || true

step "3) tools/list"
raw="$(mktemp)"
curl -sS -m45 -o "$raw" -X POST "$MCP_URL" "${hdr[@]}" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  || fail "tools/list curl failed"
tools="$(parse_sse "$raw" || true)"
[[ -n "$tools" ]] || fail "tools/list parse failed"
tools_file="$(mktemp)"
printf '%s' "$tools" > "$tools_file"

PROBE="$(python3 - "$tools_file" <<'PY'
import json, sys
from pathlib import Path
d = json.loads(Path(sys.argv[1]).read_text())
tools = (d.get("result") or {}).get("tools") or []
names = [t.get("name") for t in tools if t.get("name")]
print(len(names))
for n in names:
    if "list" in n.lower() and "test" in n.lower():
        print(n)
        raise SystemExit(0)
for n in names:
    if "list" in n.lower() and "alert" in n.lower():
        print(n)
        raise SystemExit(0)
print(names[0] if names else "")
PY
)"
count="$(echo "$PROBE" | head -1)"
tool="$(echo "$PROBE" | tail -1)"
[[ -n "$tool" ]] || fail "no tools returned (count=$count)"
ok "tools/list: $count tools; probe=$tool"

step "4) tools/call $tool"
payload="$(python3 -c "import json; print(json.dumps({'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'$tool','arguments':{}}}))")"
raw="$(mktemp)"
curl -sS -m90 -o "$raw" -X POST "$MCP_URL" "${hdr[@]}" -d "$payload" \
  || fail "tools/call curl failed"
call="$(parse_sse "$raw" || true)"
[[ -n "$call" ]] || fail "tools/call parse failed"

python3 - "$tool" <<<"$call" <<'PY'
import json, sys
tool = sys.argv[1]
d = json.loads(sys.stdin.read())
if d.get("error"):
    raise SystemExit(f"  FAIL: {tool} error: {json.dumps(d['error'])[:200]}")
r = d.get("result") or {}
if r.get("isError"):
    raise SystemExit(f"  FAIL: {tool} isError=true")
text = ""
for b in r.get("content") or []:
    if b.get("type") == "text":
        text = b.get("text") or ""
        break
preview = " ".join(text.split())[:280]
print(f"  OK: {tool} returned data")
if preview:
    print(f"  preview: {preview}")
PY

printf '\nThousandEyes MCP ping complete.\n'
