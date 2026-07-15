#!/usr/bin/env bash
# =============================================================================
# install-clawstack.sh  —  Governed OpenClaw + Cisco DefenseClaw AI-ops stack
# -----------------------------------------------------------------------------
# Interactive installer. Prompts for:
#   • install MODE:  server (LAN + Let's Encrypt TLS + PAM + npx MCP bridge)
#                    local  (everything bound to 127.0.0.1)
#   • model PROVIDERS  — iterative (name, api type, key, models)
#   • MCP servers      — iterative (name, url, bearer token)
#   • secrets          — API keys / tokens, written to per-app .env (never echoed)
#
# Bakes in the fixes learned in production:
#   • anthropic (and every manually-added) provider gets a `models: [...]` array
#     + `api: "anthropic-messages"` — WITHOUT this the gateway crashes in model
#     failover with "Cannot read properties of undefined (reading 'find')".
#   • DefenseClaw guardrail on the `strict` rule pack in `action` mode.
#   • DefenseClaw exec-shim hardening (full-command inspection) + self-heal.
#   • audit -> Webex bridge.
#   • Node >= 24.15 via NodeSource (nvm-only breaks the systemd services).
#   • openclaw.mjs symlinked into ~/.local/bin (pnpm link --global is removed).
#
# Safe to re-run; steps are guarded. Run as the user that will own the stack
# (NOT root). sudo is used only for apt / nginx / systemd-system bits.
# =============================================================================
set -Eeuo pipefail

# ---------------------------------------------------------------- ui helpers --
c_b=$'\e[1m'; c_g=$'\e[32m'; c_y=$'\e[33m'; c_r=$'\e[31m'; c_d=$'\e[2m'; c_0=$'\e[0m'
log()  { printf '%s==>%s %s\n' "$c_g$c_b" "$c_0" "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '%sWARN:%s %s\n' "$c_y" "$c_0" "$*" >&2; }
die()  { printf '%sERROR:%s %s\n' "$c_r" "$c_0" "$*" >&2; exit 1; }
ask()  { local p="$1" d="${2:-}" a; if [ -n "$d" ]; then read -r -p "  $p [$d]: " a; echo "${a:-$d}"; else read -r -p "  $p: " a; echo "$a"; fi; }
ask_secret() { local p="$1" a; read -r -s -p "  $p: " a; echo >&2; printf '%s' "$a"; }
yesno() { local p="$1" d="${2:-y}" a; read -r -p "  $p [$( [ "$d" = y ] && echo 'Y/n' || echo 'y/N' )]: " a; a="${a:-$d}"; [[ "$a" =~ ^[Yy] ]]; }

[ "$(id -u)" -ne 0 ] || die "Run as your normal user, not root (sudo is used where needed)."
command -v sudo >/dev/null || die "sudo is required."

OC_HOME="$HOME/.openclaw"
DC_HOME="$HOME/.defenseclaw"
BIN="$HOME/.local/bin"; mkdir -p "$BIN"
SRC="$HOME/src"; mkdir -p "$SRC"
OC_ENV="$OC_HOME/.env"
DC_ENV="$DC_HOME/.env"
export PATH="$BIN:$PATH"

# python helper: merge a JSON fragment into openclaw.json (deep-ish for our keys)
oc_json() { python3 - "$OC_HOME/openclaw.json" "$@"; }

# ================================================================ 0. MODE ====
echo
log "ClawStack installer"
info "Modes:  server = LAN access, Let's Encrypt TLS, PAM login, npx MCP bridge"
info "        local  = everything bound to 127.0.0.1 (governance still on)"
MODE="$(ask 'Install mode (server/local)' 'local')"
[[ "$MODE" =~ ^(server|local)$ ]] || die "mode must be 'server' or 'local'"
if [ "$MODE" = server ]; then
  FQDN="$(ask 'Public FQDN for this host (for the LE cert + UIs)')"
  LAN_IP="$(ask 'LAN IP to bind services to' "$(hostname -I 2>/dev/null | awk '{print $1}')")"
  [ -n "$FQDN" ] || die "server mode needs an FQDN"
fi

# ========================================================= 1. PREREQUISITES ==
log "Installing prerequisites"
sudo apt-get update -qq
sudo apt-get install -y -qq git curl jq python3 python3-yaml build-essential ca-certificates >/dev/null
if [ "$MODE" = server ]; then
  sudo apt-get install -y -qq nginx libnginx-mod-http-auth-pam openssl >/dev/null
fi

# Node >= 24.15 (system install via NodeSource; nvm-only would break systemd units)
need_node=24
have_node="$(node -v 2>/dev/null | sed 's/^v//; s/\..*//')"
if [ -z "$have_node" ] || [ "$have_node" -lt "$need_node" ]; then
  log "Installing Node.js $need_node.x (system-wide via NodeSource)"
  curl -fsSL "https://deb.nodesource.com/setup_${need_node}.x" | sudo -E bash - >/dev/null
  sudo apt-get install -y -qq nodejs >/dev/null
fi
info "node $(node -v)  npm $(npm -v)"
# pnpm via corepack
corepack enable >/dev/null 2>&1 || sudo npm install -g pnpm >/dev/null 2>&1 || true
command -v pnpm >/dev/null || die "pnpm not available after corepack/npm"
# lego (ACME) for server mode
if [ "$MODE" = server ] && ! command -v lego >/dev/null; then
  log "Installing lego (ACME client)"
  go_ver=""; command -v go >/dev/null && go install github.com/go-acme/lego/v4/cmd/lego@latest 2>/dev/null && go_ver=1 || true
  if [ -z "$go_ver" ]; then
    LEGO_URL="$(curl -fsSL https://api.github.com/repos/go-acme/lego/releases/latest | jq -r '.assets[]|select(.name|test("linux_amd64.tar.gz$")).browser_download_url')"
    curl -fsSL "$LEGO_URL" | tar -xz -C "$BIN" lego 2>/dev/null || warn "install lego manually into $BIN"
  fi
fi

# ============================================================== 2. OPENCLAW ==
if ! command -v openclaw >/dev/null; then
  log "Building OpenClaw from source"
  [ -d "$SRC/openclaw" ] || git clone --depth 1 https://github.com/openclaw/openclaw "$SRC/openclaw"
  ( cd "$SRC/openclaw" && pnpm install --frozen-lockfile && pnpm build )
  # symlink the CLI entrypoint (pnpm link --global is deprecated / breaks here)
  ln -sf "$SRC/openclaw/dist/index.js" "$BIN/openclaw"
  chmod +x "$BIN/openclaw" 2>/dev/null || true
fi
info "openclaw $(openclaw --version 2>/dev/null | head -1)"

# ============================================================ 3. DEFENSECLAW =
if ! command -v defenseclaw >/dev/null; then
  log "Installing Cisco DefenseClaw"
  [ -d "$SRC/defenseclaw" ] || git clone --depth 1 https://github.com/cisco-ai-defense/defenseclaw "$SRC/defenseclaw"
  # clear any release-managed markers that block a source install
  rm -f "$BIN/.defenseclaw-source-root" 2>/dev/null || true
  ( cd "$SRC/defenseclaw" && ./scripts/install.sh --replace-defenseclaw --connector openclaw 2>/dev/null \
      || make install CONNECTOR=openclaw )
fi
info "defenseclaw $(defenseclaw --version 2>/dev/null | head -1)"

# base onboarding so ~/.openclaw/openclaw.json exists
mkdir -p "$OC_HOME" "$DC_HOME"
[ -f "$OC_HOME/openclaw.json" ] || echo '{}' > "$OC_HOME/openclaw.json"
touch "$OC_ENV" "$DC_ENV"; chmod 600 "$OC_ENV" "$DC_ENV"

# =================================================== 4. MODEL PROVIDERS (loop)
log "Model providers (add one or more; blank name to finish)"
while true; do
  echo
  PNAME="$(ask 'Provider id (anthropic / ollama / openai / …; blank = done)')"
  [ -z "$PNAME" ] && break
  case "$PNAME" in
    anthropic) def_api="anthropic-messages"; def_base=""; def_img="text,image";;
    ollama)    def_api="ollama";             def_base="http://127.0.0.1:11434"; def_img="text";;
    openai)    def_api="openai-responses";   def_base=""; def_img="text,image";;
    *)         def_api="openai-completions"; def_base=""; def_img="text";;
  esac
  PAPI="$(ask "  API type for $PNAME" "$def_api")"
  PBASE="$(ask "  Base URL (blank = provider default)" "$def_base")"
  ENVVAR="$(ask "  Env var name that will hold the API key" "$(echo "$PNAME" | tr a-z A-Z)_API_KEY")"
  if [ "$PNAME" = ollama ]; then
    info "  (local ollama ignores the key; a placeholder is fine)"; PKEY="ollama"
  else
    PKEY="$(ask_secret "  API key for $PNAME (stored in $OC_ENV, not echoed)")"
  fi
  # write the secret to ~/.openclaw/.env (env var NAME is what openclaw.json references)
  grep -q "^${ENVVAR}=" "$OC_ENV" 2>/dev/null && sed -i "s|^${ENVVAR}=.*|${ENVVAR}=${PKEY}|" "$OC_ENV" \
      || echo "${ENVVAR}=${PKEY}" >> "$OC_ENV"

  MODELS="$(ask '  Model ids for this provider (comma-separated)' "$( [ "$PNAME" = anthropic ] && echo 'claude-sonnet-5,claude-haiku-4-5' || echo '' )")"
  CTX="$(ask '  Context window for these models' '200000')"

  # merge provider + a models[] array into openclaw.json  (THE anthropic .find() fix)
  oc_json "$PNAME" "$PAPI" "$PBASE" "$ENVVAR" "$MODELS" "$CTX" "$def_img" <<'PY'
import json,sys
p, name, api, base, envvar, models_csv, ctx, imgcsv = sys.argv[1:]
d=json.load(open(p))
d.setdefault("models",{}).setdefault("providers",{})
prov={"api":api,"apiKey":envvar}
if base: prov["baseUrl"]=base
inputs=[x for x in imgcsv.split(",") if x]
mlist=[]
for mid in [m.strip() for m in models_csv.split(",") if m.strip()]:
    mlist.append({
        "id":mid,"name":mid,"input":inputs,
        "contextWindow":int(ctx or 200000),"maxTokens":8192,
        "reasoning":True,
        "compat":{"supportsTools":True,"supportsUsageInStreaming":True},
        "cost":{"cacheRead":0,"cacheWrite":0,"input":0,"output":0},
    })
if mlist: prov["models"]=mlist          # <-- REQUIRED or the gateway crashes in failover
d["models"]["providers"][name]=prov
d.setdefault("models",{}).setdefault("mode","merge")
json.dump(d,open(p,"w"),indent=1)
print("  provider",name,"->",len(mlist),"model(s), api="+api)
PY
  yesno "Add another provider?" y || break
done

# ============================================ 5. MODEL TIERING (primary/fallback)
echo
log "Default model tiering"
PRIMARY="$(ask 'Primary model (provider/model)' 'ollama/llama3.1:8b')"
FALLBACKS="$(ask 'Fallback model(s), comma-separated' 'anthropic/claude-sonnet-5')"
oc_json "$PRIMARY" "$FALLBACKS" <<'PY'
import json,sys
p,primary,fb=sys.argv[1:]
d=json.load(open(p))
d.setdefault("agents",{}).setdefault("defaults",{})
d["agents"]["defaults"]["model"]={"primary":primary,"fallbacks":[x.strip() for x in fb.split(",") if x.strip()]}
json.dump(d,open(p,"w"),indent=1); print("  tiering:",primary,"->",fb)
PY

# ================================================= 6. MCP SERVERS (iterative) =
echo
log "MCP servers (register existing endpoints; blank name to finish)"
while true; do
  echo
  MNAME="$(ask 'MCP name (blank = done)')"
  [ -z "$MNAME" ] && break
  MURL="$(ask "  URL for $MNAME (e.g. https://host:8766/mcp)")"
  MTRANS="$(ask "  Transport" 'streamable-http')"
  MTOK="$(ask_secret "  Bearer token for $MNAME (blank if none)")"
  oc_json "$MNAME" "$MURL" "$MTRANS" "$MTOK" <<'PY'
import json,sys
p,name,url,trans,tok=sys.argv[1:]
d=json.load(open(p))
srv=d.setdefault("mcp",{}).setdefault("servers",{})
entry={"url":url,"transport":trans}
if tok: entry["headers"]={"Authorization":"Bearer "+tok}
srv[name]=entry
json.dump(d,open(p,"w"),indent=1); print("  registered MCP",name)
PY
  yesno "Add another MCP?" y || break
done

# ============================================ 7. GATEWAY BIND + ACCESS (mode) =
echo
log "Gateway access ($MODE mode)"
GW_TOKEN="$(openssl rand -hex 24)"
grep -q '^OPENCLAW_GATEWAY_TOKEN=' "$OC_ENV" || echo "OPENCLAW_GATEWAY_TOKEN=$GW_TOKEN" >> "$OC_ENV"
grep -q '^OPENCLAW_GATEWAY_PASSWORD=' "$OC_ENV" || echo "OPENCLAW_GATEWAY_PASSWORD=$(openssl rand -hex 24)" >> "$OC_ENV"

if [ "$MODE" = local ]; then
  oc_json <<'PY'
import json,sys
p=sys.argv[1]; d=json.load(open(p))
g=d.setdefault("gateway",{})
g["bind"]="loopback"; g["host"]="127.0.0.1"; g["port"]=18789
g.setdefault("auth",{})["mode"]="token"; g["auth"]["token"]="OPENCLAW_GATEWAY_TOKEN"
json.dump(d,open(p,"w"),indent=1); print("  gateway bound to 127.0.0.1:18789 (token auth)")
PY
else
  # server: gateway stays on loopback; nginx (PAM+LE) is the only ingress (trusted-proxy)
  oc_json "$FQDN" "$LAN_IP" <<'PY'
import json,sys
p,fqdn,lan=sys.argv[1:]; d=json.load(open(p))
g=d.setdefault("gateway",{})
g["bind"]="loopback"; g["host"]="127.0.0.1"; g["port"]=18789
g["trustedProxies"]=["127.0.0.1"]
g["auth"]={"mode":"trusted-proxy","password":"OPENCLAW_GATEWAY_PASSWORD",
           "trustedProxy":{"userHeader":"x-forwarded-user","allowUsers":[],"allowLoopback":True}}
g.setdefault("controlUi",{})["allowedOrigins"]=[f"https://{fqdn}:8444",f"https://{lan}:8444"]
json.dump(d,open(p,"w"),indent=1); print("  gateway loopback + trusted-proxy; Control UI origin",fqdn)
PY
fi

# ================================================ 8. DEFENSECLAW GOVERNANCE ===
echo
log "DefenseClaw guardrail (strict rule pack, action mode)"
defenseclaw setup guardrail --connector openclaw --mode action \
  --rule-pack strict --detection-strategy regex_judge >/dev/null 2>&1 \
  || warn "guardrail setup returned non-zero (check 'defenseclaw guardrail status')"

if yesno "Configure a Cisco Webex webhook for alerts?" y; then
  WEBEX_TOKEN="$(ask_secret '  Webex bot token')"
  WEBEX_ROOM="$(ask '  Webex room id')"
  grep -q '^DEFENSECLAW_WEBEX_TOKEN=' "$DC_ENV" || echo "DEFENSECLAW_WEBEX_TOKEN=$WEBEX_TOKEN" >> "$DC_ENV"
  defenseclaw setup webhook add --type webex --name webex \
    --url https://webexapis.com/v1/messages --room-id "$WEBEX_ROOM" \
    --secret-env DEFENSECLAW_WEBEX_TOKEN --min-severity HIGH >/dev/null 2>&1 \
    || warn "webhook add returned non-zero; add it manually"
fi

# ============================== 9. BRIDGE + SHIM-HEAL + EXTENSION SELF-HEAL ===
echo
log "Installing audit->Webex bridge, shim hardening + self-heal"
UNIT_DIR="$HOME/.config/systemd/user"; mkdir -p "$UNIT_DIR"
ASSET_BASE="${CLAWSTACK_ASSETS:-}"   # optional local dir with the repo assets

install_asset() { # src-relative-path  dest
  local rel="$1" dest="$2"
  if [ -n "$ASSET_BASE" ] && [ -f "$ASSET_BASE/$rel" ]; then install -m "${3:-644}" "$ASSET_BASE/$rel" "$dest"; return; fi
  warn "asset $rel not found (set CLAWSTACK_ASSETS to the clawlab repo); skipping $dest"
  return 1
}

# shim hardening (full-command inspection) + path-unit self-heal
mkdir -p "$DC_HOME/shims-heal"
if install_asset shim-hardening/patch-shims.sh "$DC_HOME/shims-heal/patch-shims.sh" 755; then
  "$DC_HOME/shims-heal/patch-shims.sh" || true
  install_asset shim-hardening/defenseclaw-shim-heal.service "$UNIT_DIR/defenseclaw-shim-heal.service"
  install_asset shim-hardening/defenseclaw-shim-heal.path    "$UNIT_DIR/defenseclaw-shim-heal.path"
fi
# audit -> Webex bridge
mkdir -p "$DC_HOME/webex-bridge"
if install_asset defenseclaw-webex-bridge/dc-webex-bridge.py "$DC_HOME/webex-bridge/dc-webex-bridge.py" 755; then
  install_asset defenseclaw-webex-bridge/dc-webex-bridge.service "$UNIT_DIR/dc-webex-bridge.service"
fi

# =============================================== 10. SERVER MODE: TLS + PROXY =
if [ "$MODE" = server ]; then
  echo
  log "Server mode: Let's Encrypt cert + nginx (PAM) reverse proxy"
  info "DNS-01 is recommended (works behind NAT / split-horizon DNS)."
  DNSPROV="$(ask '  lego DNS provider (e.g. godaddy, cloudflare, route53)' 'godaddy')"
  ACME_EMAIL="$(ask '  ACME account email')"
  info "  Put the provider credential env vars in ~/mcp/acme/${DNSPROV}.env (chmod 600) before issuing."
  mkdir -p "$HOME/mcp/acme"
  cat > "$HOME/mcp/acme/issue.sh" <<EOF
#!/usr/bin/env bash
set -a; . "$HOME/mcp/acme/${DNSPROV}.env"; set +a
lego --email "$ACME_EMAIL" --dns "$DNSPROV" --dns.propagation-wait 120s \\
     --domains "$FQDN" --path "$HOME/mcp/acme/lego" --accept-tos run
EOF
  chmod +x "$HOME/mcp/acme/issue.sh"
  info "  Issue the cert with:  ~/mcp/acme/issue.sh"

  # PAM service + nginx site (Control UI on :8444)
  sudo tee /etc/pam.d/openclaw-admin >/dev/null <<'EOF'
@include common-auth
@include common-account
EOF
  CERT="$HOME/mcp/acme/lego/certificates/$FQDN.crt"
  KEY="$HOME/mcp/acme/lego/certificates/$FQDN.key"
  sudo tee /etc/nginx/sites-available/openclaw-control.conf >/dev/null <<EOF
server {
    listen ${LAN_IP}:8444 ssl;
    server_name ${FQDN};
    ssl_certificate     ${CERT};
    ssl_certificate_key ${KEY};
    ssl_protocols       TLSv1.2 TLSv1.3;
    auth_pam              "OpenClaw Control (Linux login)";
    auth_pam_service_name "openclaw-admin";
    client_max_body_size 50m;
    location ^~ /assets/ { auth_pam off; proxy_pass http://127.0.0.1:18789; proxy_set_header Host \$host; }
    location / {
        proxy_pass http://127.0.0.1:18789;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-User \$remote_user;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Host \$host;
        proxy_read_timeout 3600s;
    }
}
EOF
  sudo ln -sf /etc/nginx/sites-available/openclaw-control.conf /etc/nginx/sites-enabled/
  sudo usermod -aG shadow www-data
  if [ -f "$CERT" ]; then sudo nginx -t && sudo systemctl reload nginx; else
    warn "cert not present yet — issue it (~/mcp/acme/issue.sh) then: sudo nginx -t && sudo systemctl reload nginx"; fi

  # npx MCP bridge hint for external Claude Desktop clients
  cat > "$HOME/clawstack-mcp-client.json" <<EOF
{
  "mcpServers": {
    "ssh-ops": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://${FQDN}:8766/mcp", "--header", "Authorization:\${AUTH_HEADER}"],
      "env": { "AUTH_HEADER": "Bearer <YOUR_MCP_TOKEN>" }
    }
  }
}
EOF
  info "  External MCP clients: merge ~/clawstack-mcp-client.json into their config (uses npx mcp-remote over HTTPS)."
fi

# ==================================================== 11. START + SUMMARY =====
echo
log "Enabling services"
loginctl enable-linger "$USER" >/dev/null 2>&1 || true
systemctl --user daemon-reload || true
for u in openclaw-gateway dc-webex-bridge defenseclaw-shim-heal.path; do
  systemctl --user enable --now "$u" >/dev/null 2>&1 || warn "could not enable $u (may not exist yet)"
done

echo
python3 -c "import json;d=json.load(open('$OC_HOME/openclaw.json'));print('config valid, providers:',list(d.get('models',{}).get('providers',{}).keys()),'| mcp:',list(d.get('mcp',{}).get('servers',{}).keys()))" \
  || warn "openclaw.json failed to parse — run: openclaw config validate"

cat <<EOF

${c_g}${c_b}ClawStack install complete (${MODE} mode).${c_0}
  Config:    $OC_HOME/openclaw.json   (secrets in $OC_ENV / $DC_ENV, chmod 600)
  Validate:  openclaw config validate   ·   defenseclaw guardrail status
  Gateway:   http://127.0.0.1:18789$( [ "$MODE" = server ] && echo "  (public: https://$FQDN:8444 — PAM login)" )
  Test:      openclaw agent --model <provider/model> -m "say pong"
$( [ "$MODE" = server ] && echo "  Cert:      run ~/mcp/acme/issue.sh, then reload nginx" )

  Reminder: each model provider has a models[] array + api type — required, or the
  gateway crashes in failover. Re-run this script any time to add providers/MCPs.
EOF
