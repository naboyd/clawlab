#!/usr/bin/env bash
# =============================================================================
# install-clawstack.sh  —  Governed OpenClaw + Cisco DefenseClaw AI-ops stack
# -----------------------------------------------------------------------------
# Interactive installer. Prompts for:
#   • install MODE:  local       (127.0.0.1 gateway only)
#                    local-full  (Mac/desktop: portal :8083 + MCP + claw-auth; like a Linux lab host, no LE)
#                    server      (Linux/apt legacy PAM nginx :8444 — prefer install-portals.sh)
#   • model PROVIDERS  — iterative (name, api type, key, models)
#   • MCP servers      — iterative (name, url, bearer token)
#   • DefenseClaw scan — local Ollama judge / Cisco AI Defense API / both
#   • secrets          — API keys / tokens, written to per-app .env (never echoed)
#
# Category map (vs install-portals.sh / Linux HTTPS production path):
#   KEEP here     — OpenClaw/DefenseClaw build, provider+MCP loops, gateway bind,
#                   guardrail rules, Webex webhook, shim-heal + dc-webex-bridge assets
#   REPLACE       — server nginx :8444 PAM → claw-portals/install-portals.sh (:8443)
#   MERGE later   — MCP identity proxy, refresh-clawlab-policies, ssh-ops quadlets
#   macOS         — local mode + source builds; server TLS/nginx → use Linux lab host
#
# Usage:
#   bash install/install-clawstack.sh
#   bash install/install-clawstack.sh --local-full   # interactive; Enter accepts defaults
#   bash install/install-clawstack.sh --local-full --yes   # fully non-interactive
#   bash install/install-clawstack.sh --yes          # accept all defaults (any mode)
#   bash install/install-clawstack.sh --local | --server
#   bash install/install-clawstack.sh --skip-precheck
#   bash install/preinstall-check.sh [--fix]
#
# Safe to re-run; steps are guarded. Run as the user that will own the stack
# (NOT root). sudo is used only for apt/nginx on Linux.
# =============================================================================
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib/clawlab-platform.sh
source "$SCRIPT_DIR/lib/clawlab-platform.sh"
# shellcheck source=lib/clawlab-local-full.sh
source "$SCRIPT_DIR/lib/clawlab-local-full.sh"

CLAWLAB_REPO="$(clawlab_repo_root "$0")"
export CLAWSTACK_ASSETS="${CLAWSTACK_ASSETS:-$CLAWLAB_REPO}"

# ---------------------------------------------------------------- ui helpers --
c_b=$'\e[1m'; c_g=$'\e[32m'; c_y=$'\e[33m'; c_r=$'\e[31m'; c_d=$'\e[2m'; c_0=$'\e[0m'
log()  { printf '%s==>%s %s\n' "$c_g$c_b" "$c_0" "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '%sWARN:%s %s\n' "$c_y" "$c_0" "$*" >&2; }
die()  { printf '%sERROR:%s %s\n' "$c_r" "$c_0" "$*" >&2; exit 1; }

AUTO_DEFAULTS=0
clawlab_refresh_auto_defaults() {
  AUTO_DEFAULTS=0
  [[ "${NONINTERACTIVE:-0}" -eq 1 ]] && AUTO_DEFAULTS=1
}

ask() {
  local p="$1" d="${2:-}" a
  if [[ "$AUTO_DEFAULTS" -eq 1 ]]; then
    if [[ -n "$d" ]]; then
      printf '    %s → %s\n' "$p" "$d" >&2
      echo "$d"
    else
      printf '    %s → (blank)\n' "$p" >&2
      echo ""
    fi
    return
  fi
  if [ -n "$d" ]; then read -r -p "  $p [$d]: " a; echo "${a:-$d}"; else read -r -p "  $p: " a; echo "$a"; fi
}
ask_secret() {
  local p="$1" a=""
  if [[ "$AUTO_DEFAULTS" -eq 1 ]]; then
    printf '    %s → (skipped in default mode)\n' "$p" >&2
    printf '%s' ""
    return
  fi
  read -r -s -p "  $p: " a; echo >&2; printf '%s' "$a"
}
yesno() {
  local p="$1" d="${2:-y}" a
  if [[ "$AUTO_DEFAULTS" -eq 1 ]]; then
    printf '    %s → %s (default)\n' "$p" "$d" >&2
    [[ "$d" =~ ^[Yy] ]]
    return
  fi
  read -r -p "  $p [$( [ "$d" = y ] && echo 'Y/n' || echo 'y/N' )]: " a; a="${a:-$d}"; [[ "$a" =~ ^[Yy] ]]
}

SKIP_PRECHECK=0
NONINTERACTIVE=0
MODE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-precheck) SKIP_PRECHECK=1 ;;
    --local) MODE=local ;;
    --local-full) MODE=local-full ;;
    --server) MODE=server ;;
    --mode=*) MODE="${1#*=}" ;;
    --yes|-y|--non-interactive) NONINTERACTIVE=1 ;;
    -h|--help) sed -n '1,28p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "Unknown option: $1 (try --help)" ;;
  esac
  shift
done

[[ -z "$MODE" || "$MODE" =~ ^(local|local-full|server)$ ]] \
  || die "mode must be local, local-full, or server (got: $MODE)"

clawlab_refresh_auto_defaults

[ "$(id -u)" -ne 0 ] || die "Run as your normal user, not root (sudo is used where needed)."
if [[ "$CLAWLAB_PLATFORM" == "linux" ]]; then
  command -v sudo >/dev/null || die "sudo is required on Linux."
fi

OC_HOME="$HOME/.openclaw"
DC_HOME="$HOME/.defenseclaw"
BIN="$HOME/.local/bin"; mkdir -p "$BIN"
SRC="$HOME/src"; mkdir -p "$SRC"
OC_ENV="$OC_HOME/.env"
DC_ENV="$DC_HOME/.env"
export PATH="$BIN:$HOME/.npm-global/bin:$PATH"
clawlab_prepend_openclaw_node_path || true
clawlab_prepend_uv_path

# python helper: merge a JSON fragment into openclaw.json (deep-ish for our keys)
oc_json() { python3 - "$OC_HOME/openclaw.json" "$@"; }

configure_ollama_provider() {
  local models="${1:-llama3.1:8b}"
  grep -q '^OLLAMA_API_KEY=' "$OC_ENV" 2>/dev/null || echo "OLLAMA_API_KEY=ollama" >> "$OC_ENV"
  oc_json ollama ollama "http://127.0.0.1:11434" OLLAMA_API_KEY "$models" 200000 text <<'PY'
import json,sys
p, name, api, base, envvar, models_csv, ctx, imgcsv = sys.argv[1:]
d=json.load(open(p))
d.setdefault("models",{}).setdefault("providers",{})
prov={"api":api,"apiKey":envvar,"baseUrl":base}
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
prov["models"]=mlist
d["models"]["providers"][name]=prov
d.setdefault("models",{}).setdefault("mode","merge")
json.dump(d,open(p,"w"),indent=1)
print("  provider",name,"->",len(mlist),"model(s), api="+api)
PY
  if command -v ollama >/dev/null 2>&1; then
    clawlab_ensure_ollama_model "$CLAWLAB_AGENT_OLLAMA_TAG" \
      || warn "ollama pull $CLAWLAB_AGENT_OLLAMA_TAG failed — pull manually before agent tests"
  fi
}

openclaw_has_provider() {
  local name="$1"
  python3 - "$OC_HOME/openclaw.json" "$name" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
print("yes" if sys.argv[2] in d.get("models", {}).get("providers", {}) else "no")
PY
}

# ============================================================ 0. PRECHECK ====
if [[ "$SKIP_PRECHECK" -eq 0 ]]; then
  log "Running pre-install check (use --skip-precheck to bypass)"
  bash "$SCRIPT_DIR/preinstall-check.sh" || {
    warn "Pre-install check reported issues — review recommendations above."
    if [[ "$AUTO_DEFAULTS" -eq 1 ]]; then
      warn "Continuing with defaults (--yes mode)."
    else
      yesno "Continue anyway?" n || die "Aborted. Fix issues or pass --skip-precheck."
    fi
  }
  echo
fi

# ================================================================ 0. MODE ====
echo
log "ClawStack installer ($CLAWLAB_PLATFORM)"
info "Modes:  local       = OpenClaw + DefenseClaw on 127.0.0.1 (agent only)"
info "        local-full  = + portal hub :8083, claw-auth, ssh-ops MCP/GUI (Mac/desktop)"
info "        server      = legacy Linux PAM nginx :8444 (prefer claw-portals/install-portals.sh)"
DEFAULT_MODE="local"
[[ "$CLAWLAB_PLATFORM" == "macos" ]] && DEFAULT_MODE="local-full"
if [[ -z "$MODE" ]]; then
  MODE="$(ask 'Install mode (local/local-full/server)' "$DEFAULT_MODE")"
fi
[[ "$MODE" =~ ^(local|local-full|server)$ ]] || die "mode must be local, local-full, or server"
clawlab_refresh_auto_defaults

if [[ "$AUTO_DEFAULTS" -eq 1 ]]; then
  info "Non-interactive defaults enabled (--yes)"
elif [[ "$MODE" == "local-full" ]]; then
  info "Local-full: prompts show [defaults] — press Enter to accept (portal :8083, MCP :8766, gateway :18789)"
fi

if [[ "$MODE" == "local-full" ]] && ! clawlab_local_full_supported; then
  die "local-full mode requires macOS or Linux"
fi

if [[ "$MODE" == "server" ]] && ! clawlab_server_mode_supported; then
  warn "Server mode (nginx + PAM + :8444) requires Linux with apt."
  info "On macOS, use local mode here and run claw-portals/install-portals.sh on the lab server."
  info "  bash $CLAWLAB_REPO/claw-portals/install-portals.sh"
  yesno "Switch to local mode?" y && MODE=local || die "Use install-portals.sh on a Linux lab host for HTTPS ingress."
fi

if [ "$MODE" = server ]; then
  FQDN="$(ask 'Public FQDN for this host (for the LE cert + UIs)')"
  LAN_IP="$(ask 'LAN IP to bind services to' "$(clawlab_default_lan_ip)")"
  [ -n "$FQDN" ] || die "server mode needs an FQDN"
fi

# ========================================================= 1. PREREQUISITES ==
log "Installing prerequisites ($CLAWLAB_PKG)"
clawlab_install_prereqs "$MODE"

log "Ensuring OpenClaw-compatible Node.js (recommend node@${CLAWLAB_OPENCLAW_NODE_MAJOR})"
clawlab_install_node "$CLAWLAB_OPENCLAW_NODE_MAJOR"
info "node $(node -v)  npm $(npm -v)"
clawlab_install_pnpm || die "pnpm not available — run: bash install/preinstall-check.sh --fix"
info "pnpm $(pnpm -v)"

if [ "$MODE" = server ]; then
  clawlab_install_lego || warn "install lego manually (brew install lego / go install …)"
fi

if ! clawlab_podman_ready 2>/dev/null; then
  warn "podman not ready — ssh-ops containers will need setup after install"
  info "Recommended:"
  clawlab_podman_recommend | sed 's/^/    /'
fi

# ============================================================== 2. OPENCLAW ==
if ! command -v openclaw >/dev/null; then
  log "Building OpenClaw from source"
  [ -d "$SRC/openclaw" ] || git clone --depth 1 https://github.com/openclaw/openclaw "$SRC/openclaw"
  ( cd "$SRC/openclaw" && pnpm install --frozen-lockfile && pnpm build )
  ln -sf "$SRC/openclaw/dist/index.js" "$BIN/openclaw"
  chmod +x "$BIN/openclaw" 2>/dev/null || true
fi
info "openclaw $(openclaw --version 2>/dev/null | head -1)"

# ============================================================ 3. DEFENSECLAW =
log "Ensuring uv (DefenseClaw installer)"
clawlab_install_uv || die "uv not available — run: bash install/preinstall-check.sh --fix"
info "uv $(uv --version 2>/dev/null | head -1)"

if ! command -v defenseclaw >/dev/null; then
  log "Installing Cisco DefenseClaw"
  [ -d "$SRC/defenseclaw" ] || git clone --depth 1 https://github.com/cisco-ai-defense/defenseclaw "$SRC/defenseclaw"
  rm -f "$BIN/.defenseclaw-source-root" 2>/dev/null || true
  if ! ( cd "$SRC/defenseclaw" && ./scripts/install.sh --yes --connector openclaw ); then
    die "DefenseClaw install failed — ensure uv and Python 3.12 are available (see output above)"
  fi
fi
info "defenseclaw $(defenseclaw --version 2>/dev/null | head -1)"

mkdir -p "$OC_HOME" "$DC_HOME"
[ -f "$OC_HOME/openclaw.json" ] || echo '{}' > "$OC_HOME/openclaw.json"
touch "$OC_ENV" "$DC_ENV"; chmod 600 "$OC_ENV" "$DC_ENV"

# =================================================== 4. MODEL PROVIDERS (loop)
if [[ "$AUTO_DEFAULTS" -eq 1 ]]; then
  log "Model providers (defaults: ollama / llama3.1:8b)"
  if [[ "$(openclaw_has_provider ollama)" == yes ]]; then
    info "  ollama provider already configured — keeping existing"
  else
    configure_ollama_provider "llama3.1:8b"
  fi
elif [[ "$MODE" == "local-full" ]] && yesno "Use default model provider (ollama / llama3.1:8b)?" y; then
  log "Model providers (local-full default: ollama / llama3.1:8b)"
  if [[ "$(openclaw_has_provider ollama)" == yes ]]; then
    info "  ollama provider already configured — keeping existing"
  else
    configure_ollama_provider "llama3.1:8b"
  fi
else
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
    if grep -q "^${ENVVAR}=" "$OC_ENV" 2>/dev/null; then
      clawlab_sed_inplace "s|^${ENVVAR}=.*|${ENVVAR}=${PKEY}|" "$OC_ENV"
    else
      echo "${ENVVAR}=${PKEY}" >> "$OC_ENV"
    fi

    MODELS="$(ask '  Model ids for this provider (comma-separated)' "$( [ "$PNAME" = anthropic ] && echo 'claude-sonnet-5,claude-haiku-4-5' || echo '' )")"
    CTX="$(ask '  Context window for these models' '200000')"

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
if mlist: prov["models"]=mlist
d["models"]["providers"][name]=prov
d.setdefault("models",{}).setdefault("mode","merge")
json.dump(d,open(p,"w"),indent=1)
print("  provider",name,"->",len(mlist),"model(s), api="+api)
PY
    yesno "Add another provider?" y || break
  done
fi

# ============================================ 5. MODEL TIERING (primary/fallback)
echo
log "Default model tiering"
if [[ "$AUTO_DEFAULTS" -eq 1 ]]; then
  PRIMARY="ollama/llama3.1:8b"
  FALLBACKS=""
  info "  primary → $PRIMARY (no cloud fallbacks in default local-full profile)"
else
  PRIMARY="$(ask 'Primary model (provider/model)' 'ollama/llama3.1:8b')"
  FB_DEFAULT="anthropic/claude-sonnet-5"
  [[ "$MODE" == "local-full" ]] && FB_DEFAULT=""
  FALLBACKS="$(ask 'Fallback model(s), comma-separated (blank = none)' "$FB_DEFAULT")"
fi
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
if [[ "$AUTO_DEFAULTS" -eq 1 && "$MODE" == "local-full" ]]; then
  log "MCP servers (local-full auto-registers ssh-ops at http://127.0.0.1:8766/mcp)"
elif [[ "$AUTO_DEFAULTS" -eq 1 ]]; then
  log "MCP servers (skipped in default mode — re-run without --yes to add)"
elif [[ "$MODE" == "local-full" ]]; then
  log "MCP servers (ssh-ops auto-registers after stack start)"
  info "  ssh-ops GUI :8765  ·  MCP API http://127.0.0.1:8766/mcp  ·  portal /ssh-ops/ on :${LOCAL_FULL_PORT:-8083}"
  if yesno "Manually register additional MCP servers now?" n; then
    while true; do
      echo
      MNAME="$(ask 'MCP name (blank = done)')"
      [ -z "$MNAME" ] && break
      MURL="$(ask "  URL for $MNAME" 'http://127.0.0.1:8766/mcp')"
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
  fi
else
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
fi

# ============================================ 7. GATEWAY BIND + ACCESS (mode) =
echo
log "Gateway access ($MODE mode)"
GW_TOKEN="$(openssl rand -hex 24)"
grep -q '^OPENCLAW_GATEWAY_TOKEN=' "$OC_ENV" || echo "OPENCLAW_GATEWAY_TOKEN=$GW_TOKEN" >> "$OC_ENV"
grep -q '^OPENCLAW_GATEWAY_PASSWORD=' "$OC_ENV" || echo "OPENCLAW_GATEWAY_PASSWORD=$(openssl rand -hex 24)" >> "$OC_ENV"

if [[ "$MODE" == local || "$MODE" == local-full ]]; then
  oc_json <<'PY'
import json,sys
p=sys.argv[1]; d=json.load(open(p))
g=d.setdefault("gateway",{})
g["mode"]="local"
g["bind"]="loopback"; g["port"]=18789
g.pop("host", None)
g.setdefault("auth",{})["mode"]="token"; g["auth"]["token"]="OPENCLAW_GATEWAY_TOKEN"
json.dump(d,open(p,"w"),indent=1); print("  gateway mode=local, bound to loopback:18789 (token auth)")
PY
else
  oc_json "$FQDN" "$LAN_IP" <<'PY'
import json,sys
p,fqdn,lan=sys.argv[1:]; d=json.load(open(p))
g=d.setdefault("gateway",{})
g["bind"]="loopback"; g["port"]=18789
g.pop("host", None)
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
info "Semantic inspection backend (separate from OpenClaw agent model above):"
info "  local — Ollama Foundation-Sec LLM judge (air-gapped default)"
info "  cisco — Cisco AI Defense cloud API only (no local judge model)"
info "  both  — local judge + Cisco cloud (strictest)"
SCAN_BACKEND="$(ask 'DefenseClaw scan backend (local/cisco/both)' 'local')"
case "$SCAN_BACKEND" in
  local|cisco|both) ;;
  *) die "scan backend must be local, cisco, or both" ;;
esac

DC_SETUP=(
  setup guardrail --connector openclaw --mode action
  --rule-pack strict --detection-strategy regex_judge --non-interactive
)
JUDGE_ENABLED=true
case "$SCAN_BACKEND" in
  local)
    DC_SETUP+=(--scanner-mode local)
    ;;
  cisco)
    DC_SETUP+=(--scanner-mode remote
      --cisco-endpoint "$CLAWLAB_CISCO_AID_ENDPOINT"
      --cisco-api-key-env "$CLAWLAB_CISCO_AID_KEY_ENV"
      --cisco-timeout-ms 3000)
    JUDGE_ENABLED=false
    ;;
  both)
    DC_SETUP+=(--scanner-mode both
      --cisco-endpoint "$CLAWLAB_CISCO_AID_ENDPOINT"
      --cisco-api-key-env "$CLAWLAB_CISCO_AID_KEY_ENV"
      --cisco-timeout-ms 3000)
    ;;
esac

if [[ "$SCAN_BACKEND" == cisco || "$SCAN_BACKEND" == both ]]; then
  if grep -q "^${CLAWLAB_CISCO_AID_KEY_ENV}=" "$DC_ENV" 2>/dev/null \
     && yesno "  ${CLAWLAB_CISCO_AID_KEY_ENV} already in $DC_ENV — keep it?" y; then
    info "  using existing ${CLAWLAB_CISCO_AID_KEY_ENV}"
  else
    CISCO_KEY="$(ask_secret "  Cisco AI Defense API key (${CLAWLAB_CISCO_AID_KEY_ENV})")"
    if grep -q "^${CLAWLAB_CISCO_AID_KEY_ENV}=" "$DC_ENV" 2>/dev/null; then
      clawlab_sed_inplace "s|^${CLAWLAB_CISCO_AID_KEY_ENV}=.*|${CLAWLAB_CISCO_AID_KEY_ENV}=${CISCO_KEY}|" "$DC_ENV"
    else
      echo "${CLAWLAB_CISCO_AID_KEY_ENV}=${CISCO_KEY}" >> "$DC_ENV"
    fi
  fi
fi

if [[ "$JUDGE_ENABLED" == true ]]; then
  if ! command -v ollama >/dev/null 2>&1; then
    warn "ollama not on PATH — install from https://ollama.com then run:"
    info "  ollama pull $CLAWLAB_JUDGE_OLLAMA_TAG"
  else
    log "Pulling DefenseClaw judge model ($CLAWLAB_JUDGE_OLLAMA_TAG)"
    clawlab_ensure_ollama_model "$CLAWLAB_JUDGE_OLLAMA_TAG" \
      || warn "ollama pull failed — judge may be unavailable until model is present"
  fi
fi

defenseclaw "${DC_SETUP[@]}" >/dev/null 2>&1 \
  || warn "guardrail setup returned non-zero (check 'defenseclaw guardrail status')"

SCANNER_MODE="$SCAN_BACKEND"
[[ "$SCAN_BACKEND" == local ]] && SCANNER_MODE="local"
[[ "$SCAN_BACKEND" == cisco ]] && SCANNER_MODE="remote"
[[ "$SCAN_BACKEND" == both ]] && SCANNER_MODE="both"
if clawlab_patch_defenseclaw_config "$SCANNER_MODE" "$JUDGE_ENABLED" "$CLAWLAB_JUDGE_DC_MODEL"; then
  info "  guardrail config: scanner_mode=$SCANNER_MODE judge=$JUDGE_ENABLED"
else
  warn "could not patch ~/.defenseclaw/config.yaml (install python3-yaml or edit via DefenseClaw web GUI)"
fi

if [ -f "$CLAWLAB_REPO/admin-access/install-clawlab-guardrail-rules.sh" ]; then
  bash "$CLAWLAB_REPO/admin-access/install-clawlab-guardrail-rules.sh" \
    || warn "clawlab guardrail rules install failed"
fi

if [[ "$AUTO_DEFAULTS" -eq 1 ]]; then
  if [[ -n "${DEFENSECLAW_WEBEX_TOKEN:-}" && -n "${DEFENSECLAW_WEBEX_ROOM_ID:-}" ]]; then
    log "Webex webhook (from environment)"
    grep -q '^DEFENSECLAW_WEBEX_TOKEN=' "$DC_ENV" || echo "DEFENSECLAW_WEBEX_TOKEN=${DEFENSECLAW_WEBEX_TOKEN}" >> "$DC_ENV"
    defenseclaw setup webhook add --type webex --name webex \
      --url https://webexapis.com/v1/messages --room-id "$DEFENSECLAW_WEBEX_ROOM_ID" \
      --secret-env DEFENSECLAW_WEBEX_TOKEN --min-severity HIGH >/dev/null 2>&1 \
      || warn "webhook add returned non-zero; add it manually"
  else
    info "Webex alerts skipped (set DEFENSECLAW_WEBEX_TOKEN + DEFENSECLAW_WEBEX_ROOM_ID to enable)"
  fi
elif yesno "Configure a Cisco Webex webhook for alerts?" "$([ "$MODE" = local-full ] && echo n || echo y)"; then
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
ASSET_BASE="${CLAWSTACK_ASSETS}"

install_asset() {
  local rel="$1" dest="$2"
  if [ -f "$ASSET_BASE/$rel" ]; then install -m "${3:-644}" "$ASSET_BASE/$rel" "$dest"; return; fi
  warn "asset $rel not found under $ASSET_BASE; skipping $dest"
  return 1
}

mkdir -p "$DC_HOME/shims-heal"
if install_asset shim-hardening/patch-shims.sh "$DC_HOME/shims-heal/patch-shims.sh" 755; then
  "$DC_HOME/shims-heal/patch-shims.sh" || true
  install_asset shim-hardening/defenseclaw-shim-heal.service "$UNIT_DIR/defenseclaw-shim-heal.service"
  install_asset shim-hardening/defenseclaw-shim-heal.path    "$UNIT_DIR/defenseclaw-shim-heal.path"
fi
mkdir -p "$DC_HOME/webex-bridge"
if install_asset defenseclaw-webex-bridge/dc-webex-bridge.py "$DC_HOME/webex-bridge/dc-webex-bridge.py" 755; then
  install_asset defenseclaw-webex-bridge/dc-webex-bridge.service "$UNIT_DIR/dc-webex-bridge.service"
fi

# =============================================== 10. SERVER MODE: TLS + PROXY =
if [ "$MODE" = server ]; then
  echo
  log "Server mode: Let's Encrypt cert + nginx (PAM) reverse proxy"
  warn "For new deployments prefer: bash $CLAWLAB_REPO/claw-portals/install-portals.sh"
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
if [[ "$MODE" == "local-full" && "$AUTO_DEFAULTS" -eq 0 ]]; then
  log "Local-full portal layout (loopback hub + nginx)"
  info "  Portal hub :${LOCAL_FULL_PORT:-8083}  ·  OpenClaw gateway :18789"
  info "  ssh-ops Admin GUI :8765  ·  MCP API :8766  ·  DefenseClaw :8770"
  LOCAL_FULL_DOMAIN="$(ask 'Portal bind address' '127.0.0.1')"
  LOCAL_FULL_PORT="$(ask 'Portal hub port (nginx listens here)' '8083')"
  export LOCAL_FULL_DOMAIN LOCAL_FULL_PORT
fi
if [[ "$MODE" == "local-full" ]]; then
  clawlab_install_local_full "$CLAWLAB_REPO"
elif [[ "$MODE" == "local" ]]; then
  log "Enabling services (systemd user units where available)"
  clawlab_enable_user_units openclaw-gateway dc-webex-bridge defenseclaw-shim-heal.path
  if [[ "$CLAWLAB_SVC" != "systemd-user" ]]; then
    info "Start gateway manually: openclaw gateway start"
  fi
else
  log "Enabling services"
  clawlab_enable_user_units openclaw-gateway dc-webex-bridge defenseclaw-shim-heal.path
fi

echo
python3 -c "import json;d=json.load(open('$OC_HOME/openclaw.json'));print('config valid, providers:',list(d.get('models',{}).get('providers',{}).keys()),'| mcp:',list(d.get('mcp',{}).get('servers',{}).keys()))" \
  || warn "openclaw.json failed to parse — run: openclaw config validate"

MAC_NOTE=""
if [[ "$CLAWLAB_PLATFORM" == "macos" && "$MODE" == "local" ]]; then
  MAC_NOTE="
  macOS local:  Gateway only. For portal + MCP with portal + MCP, re-run and choose local-full:
                bash $SCRIPT_DIR/install-clawstack.sh
  Or start ssh-ops manually: bash $CLAWLAB_REPO/ssh-ops-mcp/podctl.sh --build"
fi
LOCAL_FULL_NOTE=""
if [[ "$MODE" == "local-full" ]]; then
  LOCAL_FULL_NOTE="
  Portal hub: http://${LOCAL_FULL_DOMAIN:-127.0.0.1}:${LOCAL_FULL_PORT:-8083}/  ·  ctl: bash $SCRIPT_DIR/local-full-ctl.sh status
  First OpenClaw visit: hub → Open OpenClaw ↗ → OpenClaw devices tab → Approve
  Mac policy: bash $SCRIPT_DIR/local-full-ctl.sh doctor  ·  cd tests && ./policy-test.sh --no-agent
  Verify: bash $SCRIPT_DIR/verify-local-full.sh"
fi

cat <<EOF

${c_g}${c_b}ClawStack install complete (${MODE} mode on ${CLAWLAB_PLATFORM}).${c_0}
  Config:    $OC_HOME/openclaw.json   (secrets in $OC_ENV / $DC_ENV, chmod 600)
  Validate:  openclaw config validate   ·   defenseclaw guardrail status
  DC scan:   ${SCAN_BACKEND} (scanner_mode=${SCANNER_MODE}, judge=${JUDGE_ENABLED})
  Gateway:   http://127.0.0.1:18789$( [ "$MODE" = server ] && echo "  (public: https://$FQDN:8444 — PAM login)" )
  Precheck:  bash $SCRIPT_DIR/preinstall-check.sh
  Test:      openclaw agent --model <provider/model> -m "say pong"
$( [ "$MODE" = server ] && echo "  Cert:      run ~/mcp/acme/issue.sh, then reload nginx" )
${LOCAL_FULL_NOTE}
${MAC_NOTE}

  Reminder: each model provider has a models[] array + api type — required, or the
  gateway crashes in failover. Re-run this script any time to add providers/MCPs.
EOF
