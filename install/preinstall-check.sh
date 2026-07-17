#!/usr/bin/env bash
# preinstall-check.sh — verify clawlab prerequisites; print recommended fixes.
#
# Does not auto-install unless --fix is passed (and only for safe, known packages).
#
# Usage:
#   bash install/preinstall-check.sh
#   bash install/preinstall-check.sh --fix          # apt/brew only, conservative
#   bash install/preinstall-check.sh --mode=server  # include server/TLS checks
#
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib/clawlab-platform.sh
source "$SCRIPT_DIR/lib/clawlab-platform.sh"

REPO="$(clawlab_repo_root "$0")"
MODE="${MODE:-local}"
FIX=0
NEED_NODE=24
FAILED=0
WARNED=0
FOUND_ITEMS=()
NEEDED_ITEMS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --fix) FIX=1 ;;
    --mode=*) MODE="${1#*=}" ;;
    -h|--help)
      sed -n '1,12p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
  shift
done

pass() { printf '  OK   %s\n' "$*"; FOUND_ITEMS+=("$1"); }
warn() { printf '  WARN %s\n' "$*" >&2; WARNED=$((WARNED + 1)); }
fail() { printf '  FAIL %s\n' "$*" >&2; FAILED=$((FAILED + 1)); }
rec()  { printf '       -> %s\n' "$*"; }
need_item() { NEEDED_ITEMS+=("$1"); }

maybe_fix() {
  local cmd="$1"
  if [[ "$FIX" -eq 1 ]]; then
    echo "       (running: $cmd)"
    eval "$cmd" || warn "fix command failed: $cmd"
  fi
}

print_checklist_summary() {
  echo "=============================================="
  echo " install checklist"
  echo "=============================================="
  if [[ ${#FOUND_ITEMS[@]} -gt 0 ]]; then
    echo "Ready (found):"
    local item
    for item in "${FOUND_ITEMS[@]}"; do
      printf '  [ok] %s\n' "$item"
    done
  fi
  if [[ ${#NEEDED_ITEMS[@]} -gt 0 ]]; then
    echo
    echo "Still needed to complete install:"
    for item in "${NEEDED_ITEMS[@]}"; do
      printf '  [ ] %s\n' "$item"
    done
  fi
  echo "=============================================="
}

echo "=============================================="
echo " clawlab pre-install check"
echo " platform: $CLAWLAB_PLATFORM ($CLAWLAB_OS / $CLAWLAB_ARCH)"
echo " pkg:      $CLAWLAB_PKG   services: $CLAWLAB_SVC"
echo " repo:     $REPO"
echo " mode:     $MODE"
echo " time:     $(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date)"
echo "=============================================="
echo

echo "--- core tools ---"
for cmd in git curl jq python3; do
  if command -v "$cmd" >/dev/null 2>&1; then
    pass "$cmd installed"
  else
    fail "$cmd not found"
    need_item "$cmd (core tool)"
    case "$CLAWLAB_PKG" in
      apt) rec "sudo apt-get install -y $cmd"; maybe_fix "sudo apt-get install -y $cmd" ;;
      brew) rec "brew install $cmd"; maybe_fix "brew install $cmd" ;;
      *) rec "install $cmd via your OS package manager" ;;
    esac
  fi
done

if python3 -m venv -h >/dev/null 2>&1; then
  pass "python3 venv module"
else
  fail "python3-venv not available"
  need_item "python3-venv"
  case "$CLAWLAB_PKG" in
    apt) rec "sudo apt-get install -y python3-venv python3-full"; maybe_fix "sudo apt-get install -y python3-venv python3-full" ;;
    brew) rec "brew install python@3.12 (includes venv)"; maybe_fix "brew install python@3.12" ;;
  esac
fi

if python3 -c "import yaml" 2>/dev/null; then
  pass "python3 PyYAML (DefenseClaw config patch)"
else
  warn "python3-yaml missing — DefenseClaw config auto-patch may fail"
  need_item "python3-yaml (pip install pyyaml or apt install python3-yaml)"
  case "$CLAWLAB_PKG" in
    apt) rec "sudo apt-get install -y python3-yaml"; maybe_fix "sudo apt-get install -y python3-yaml" ;;
    *) rec "pip install pyyaml" ;;
  esac
fi
echo

echo "--- node / pnpm (need >= $NEED_NODE) ---"
if command -v node >/dev/null 2>&1; then
  maj="$(clawlab_node_major)"
  if [[ -n "$maj" && "$maj" -ge "$NEED_NODE" ]]; then
    pass "node >= v${NEED_NODE} ($(node -v))"
  else
    fail "node $(node -v) — need >= v${NEED_NODE}"
    need_item "Node.js >= v${NEED_NODE}"
    case "$CLAWLAB_PKG" in
      apt) rec "curl -fsSL https://deb.nodesource.com/setup_${NEED_NODE}.x | sudo -E bash - && sudo apt-get install -y nodejs" ;;
      brew) rec "brew install node@${NEED_NODE}" ;;
    esac
    [[ "$FIX" -eq 1 ]] && clawlab_install_node "$NEED_NODE" || true
  fi
else
  fail "node not found"
  need_item "Node.js >= v${NEED_NODE}"
  [[ "$FIX" -eq 1 ]] && clawlab_install_node "$NEED_NODE" || rec "install Node.js >= $NEED_NODE"
fi

if command -v pnpm >/dev/null 2>&1; then
  pass "pnpm ($(pnpm -v))"
elif [[ "$FIX" -eq 1 ]] && command -v node >/dev/null 2>&1; then
  echo "       (running: clawlab_install_pnpm)"
  if clawlab_install_pnpm; then
    pass "pnpm ($(pnpm -v))"
  else
    fail "pnpm install failed (tried corepack and npm -g)"
    need_item "pnpm"
    rec "corepack enable && corepack prepare pnpm@latest --activate"
    rec "or: npm install -g pnpm"
  fi
else
  need_item "pnpm"
  if command -v node >/dev/null 2>&1; then
    warn "pnpm not found (Node.js is present — enable corepack or npm -g pnpm)"
    rec "corepack enable && corepack prepare pnpm@latest --activate"
    rec "or: npm install -g pnpm"
    rec "or re-run: bash install/preinstall-check.sh --fix"
  else
    fail "pnpm not found (install Node.js first)"
    rec "re-run with --fix after Node.js >= $NEED_NODE is installed"
  fi
fi
echo

echo "--- ollama / LLM models ---"
if command -v ollama >/dev/null 2>&1; then
  pass "ollama CLI"
  if ollama list >/dev/null 2>&1; then
    if clawlab_ollama_has_model "$CLAWLAB_AGENT_OLLAMA_TAG"; then
      pass "agent model $CLAWLAB_AGENT_OLLAMA_TAG"
    else
      warn "agent model $CLAWLAB_AGENT_OLLAMA_TAG not pulled"
      need_item "ollama pull $CLAWLAB_AGENT_OLLAMA_TAG (OpenClaw primary)"
      rec "ollama pull $CLAWLAB_AGENT_OLLAMA_TAG"
      maybe_fix "ollama pull '$CLAWLAB_AGENT_OLLAMA_TAG'"
    fi
    if clawlab_ollama_has_model "$CLAWLAB_JUDGE_OLLAMA_TAG"; then
      pass "judge model $CLAWLAB_JUDGE_OLLAMA_TAG"
    else
      warn "judge model $CLAWLAB_JUDGE_OLLAMA_TAG not pulled"
      need_item "ollama pull $CLAWLAB_JUDGE_OLLAMA_TAG (DefenseClaw local judge)"
      rec "ollama pull $CLAWLAB_JUDGE_OLLAMA_TAG"
      maybe_fix "ollama pull '$CLAWLAB_JUDGE_OLLAMA_TAG'"
    fi
  else
    warn "ollama installed but 'ollama list' failed — is the daemon running?"
    need_item "ollama service running (ollama serve / app started)"
  fi
else
  warn "ollama not found (required for local OpenClaw + DefenseClaw judge)"
  need_item "ollama (https://ollama.com) for local agent/judge models"
  rec "install ollama, then: ollama pull $CLAWLAB_AGENT_OLLAMA_TAG"
fi
echo

echo "--- openclaw / defenseclaw ---"
if command -v openclaw >/dev/null 2>&1; then
  pass "openclaw CLI"
else
  warn "openclaw CLI not on PATH"
  need_item "openclaw CLI (bash $REPO/install/install-clawstack.sh)"
  rec "bash $REPO/install/install-clawstack.sh   # or build from ~/src/openclaw"
fi

OC_CFG="$HOME/.openclaw/openclaw.json"
if [[ -f "$OC_CFG" ]]; then
  pass "openclaw.json present"
  if python3 -c "import json; d=json.load(open('$OC_CFG')); exit(0 if d.get('models',{}).get('providers') else 1)" 2>/dev/null; then
    pass "openclaw model providers configured"
  else
    warn "openclaw.json has no model providers"
    need_item "model providers in ~/.openclaw/openclaw.json (install-clawstack.sh prompts)"
  fi
else
  warn "openclaw.json missing"
  need_item "~/.openclaw/openclaw.json (run install-clawstack.sh)"
fi

if command -v defenseclaw >/dev/null 2>&1; then
  pass "defenseclaw CLI"
else
  warn "defenseclaw CLI not on PATH"
  need_item "defenseclaw CLI (clone ~/src/defenseclaw && ./scripts/install.sh)"
  rec "clone https://github.com/cisco-ai-defense/defenseclaw to ~/src/defenseclaw && ./scripts/install.sh"
fi

DC_CFG="$HOME/.defenseclaw/config.yaml"
DC_ENV="$HOME/.defenseclaw/.env"
if [[ -f "$DC_CFG" ]]; then
  pass "defenseclaw config.yaml"
  scanner_mode="$(grep -E '^\s*scanner_mode:' "$DC_CFG" 2>/dev/null | head -1 | awk '{print $2}' | tr -d \"'\" || true)"
  judge_enabled="$(grep -E '^\s*enabled:' "$DC_CFG" 2>/dev/null | head -1 | awk '{print $2}' | tr -d \"'\" || true)"
  if [[ -n "$scanner_mode" ]]; then
    pass "DefenseClaw scanner_mode=$scanner_mode"
  else
    warn "DefenseClaw scanner_mode not set"
    need_item "defenseclaw setup guardrail (install-clawstack.sh section 8)"
  fi
  if grep -qE '^\s*model:\s*ollama/.*Foundation-Sec' "$DC_CFG" 2>/dev/null \
     || grep -A20 'judge:' "$DC_CFG" 2>/dev/null | grep -q 'Foundation-Sec'; then
    pass "DefenseClaw judge model configured"
  elif [[ "$scanner_mode" == "remote" ]]; then
    pass "DefenseClaw cloud-only scan (no local judge expected)"
  else
    warn "DefenseClaw judge model not configured"
    need_item "DefenseClaw judge (local/both backend in install-clawstack.sh)"
  fi
  if [[ "$scanner_mode" == "remote" || "$scanner_mode" == "both" ]]; then
    if [[ -f "$DC_ENV" ]] && grep -q "^${CLAWLAB_CISCO_AID_KEY_ENV}=" "$DC_ENV" 2>/dev/null; then
      pass "${CLAWLAB_CISCO_AID_KEY_ENV} in ~/.defenseclaw/.env"
    else
      warn "${CLAWLAB_CISCO_AID_KEY_ENV} missing for scanner_mode=$scanner_mode"
      need_item "${CLAWLAB_CISCO_AID_KEY_ENV} in ~/.defenseclaw/.env (Cisco AI Defense API)"
    fi
  fi
else
  warn "defenseclaw config.yaml missing"
  need_item "~/.defenseclaw/config.yaml (run install-clawstack.sh section 8)"
fi
echo

echo "--- podman (ssh-ops containers) ---"
if command -v podman >/dev/null 2>&1; then
  pass "podman CLI"
  if clawlab_podman_ready; then
    pass "podman runtime ready"
    if podman image exists ssh-ops:latest >/dev/null 2>&1; then
      pass "ssh-ops:latest image"
    else
      warn "ssh-ops:latest image missing"
      need_item "ssh-ops Podman image (podman build -t ssh-ops:latest $REPO/ssh-ops-mcp)"
      rec "podman build -t ssh-ops:latest $REPO/ssh-ops-mcp"
      maybe_fix "podman build -t ssh-ops:latest '$REPO/ssh-ops-mcp'"
    fi
  else
    fail "podman installed but not running"
    need_item "podman runtime (podman machine start / podman.socket)"
    if [[ "$CLAWLAB_PLATFORM" == "macos" ]]; then
      rec "podman machine start"
      maybe_fix "podman machine start"
    else
      rec "systemctl --user start podman.socket  # or: podman info"
    fi
  fi
else
  warn "podman not found (required for ssh-ops MCP/GUI on lab hosts)"
  need_item "podman (ssh-ops MCP/GUI containers)"
  echo "       Recommended:"
  clawlab_podman_recommend | sed 's/^/       /'
  if [[ "$CLAWLAB_PKG" == "brew" && "$FIX" -eq 1 ]]; then
    maybe_fix "brew install podman"
    maybe_fix "podman machine init 2>/dev/null || true"
    maybe_fix "podman machine start"
  elif [[ "$CLAWLAB_PKG" == "apt" && "$FIX" -eq 1 ]]; then
    maybe_fix "sudo apt-get install -y podman"
  fi
fi
echo

echo "--- python venv (~/.clawlab/venv) ---"
VENV="${CLAWLAB_VENV:-$HOME/.clawlab/venv}"
if [[ -x "$VENV/bin/python" ]]; then
  pass "clawlab venv"
  if "$VENV/bin/python" -c "import httpx, uvicorn" 2>/dev/null; then
    pass "ssh-ops-mcp deps (httpx, uvicorn)"
  else
    warn "missing ssh-ops-mcp Python deps"
    need_item "ssh-ops-mcp Python deps ($VENV/bin/pip install -r $REPO/ssh-ops-mcp/requirements.txt)"
    rec "$VENV/bin/pip install -r $REPO/ssh-ops-mcp/requirements.txt"
    maybe_fix "'$VENV/bin/pip' install -r '$REPO/ssh-ops-mcp/requirements.txt'"
  fi
else
  warn "clawlab venv missing"
  need_item "clawlab venv (bash $REPO/claw-portals/ensure-venv.sh)"
  rec "bash $REPO/claw-portals/ensure-venv.sh"
  maybe_fix "bash '$REPO/claw-portals/ensure-venv.sh'"
fi
echo

echo "--- services (systemd user) ---"
if [[ "$CLAWLAB_SVC" == "systemd-user" ]]; then
  pass "systemd --user"
  for u in openclaw-gateway claw-auth defenseclaw-webgui ssh-ops-gui mcp-identity-proxy; do
    if systemctl --user is-active "$u.service" >/dev/null 2>&1; then
      pass "$u.service active"
    elif systemctl --user list-unit-files "$u.service" >/dev/null 2>&1; then
      warn "$u installed but not active"
      need_item "systemctl --user restart $u"
      rec "systemctl --user restart $u"
    else
      warn "$u unit not installed"
      need_item "$u systemd user unit (install-clawstack.sh / install-portals.sh)"
    fi
  done
elif [[ "$CLAWLAB_PLATFORM" == "macos" ]]; then
  warn "macOS has no systemd user units — use podctl.sh or podman run for ssh-ops"
  need_item "manual service start on macOS (openclaw gateway start; ssh-ops-mcp/podctl.sh)"
  rec "$REPO/ssh-ops-mcp/podctl.sh --status"
  rec "openclaw gateway start   # if running OpenClaw locally"
else
  warn "systemd user session not detected"
fi
echo

echo "--- portal / auth (production path) ---"
if [[ -f "$HOME/.claw-portals/config.env" ]]; then
  pass "unified portal config (~/.claw-portals/config.env)"
  grep -E '^(TLS_MODE|AUTH_MODE|PORT_)' "$HOME/.claw-portals/config.env" 2>/dev/null | sed 's/^/       /' || true
else
  warn "unified portal not configured"
  need_item "HTTPS portal (bash $REPO/claw-portals/install-portals.sh)"
  rec "bash $REPO/claw-portals/install-portals.sh --non-interactive --tls=https-le --auth=claw-auth"
fi
if curl -fsS "http://127.0.0.1:8780/healthz" >/dev/null 2>&1; then
  pass "claw-auth healthz (:8780)"
else
  warn "claw-auth not responding on :8780"
  need_item "claw-auth running (install-portals.sh)"
fi
echo

if [[ "$MODE" == "server" ]]; then
  echo "--- server mode (TLS / nginx) ---"
  if clawlab_server_mode_supported; then
    pass "legacy install-clawstack server mode supported"
    command -v nginx >/dev/null && pass "nginx installed" || { fail "nginx missing"; need_item "nginx"; rec "sudo apt-get install -y nginx"; }
    command -v lego >/dev/null && pass "lego installed" || { warn "lego missing"; need_item "lego (ACME DNS-01)"; rec "see install-clawstack.sh or: go install github.com/go-acme/lego/v4/cmd/lego@latest"; }
  else
    warn "install-clawstack server mode (PAM nginx :8444) is Linux/apt only"
    need_item "Linux lab host for HTTPS ingress (claw-portals/install-portals.sh)"
    rec "Use $REPO/claw-portals/install-portals.sh on the lab server (unified :8443 + claw-auth)"
    rec "On macOS dev: run local mode + podman; deploy portals on icecream"
  fi
  echo
fi

echo "--- clawlab repo assets ---"
for f in admin-access/install-clawlab-guardrail-rules.sh \
         admin-access/refresh-clawlab-policies.sh \
         admin-access/configure-openclaw-mcp-identity.sh \
         quadlets/ssh-ops-gui.container; do
  if [[ -f "$REPO/$f" ]]; then pass "$f"; else fail "missing $f"; need_item "$f in clawlab repo"; fi
done
echo

print_checklist_summary

if [[ "$FAILED" -gt 0 ]]; then
  echo "Result: $FAILED blocking issue(s), $WARNED warning(s), ${#NEEDED_ITEMS[@]} item(s) still needed"
  echo "Fix blockers, then re-run. Use --fix for conservative auto-install (apt/brew only)."
  exit 1
fi
if [[ "$WARNED" -gt 0 || ${#NEEDED_ITEMS[@]} -gt 0 ]]; then
  echo "Result: ready with $WARNED warning(s), ${#NEEDED_ITEMS[@]} item(s) still needed — review checklist above."
  echo "Next:   bash $REPO/install/install-clawstack.sh"
  exit 0
fi
echo "Result: all checks passed — ready for install-clawstack.sh"
exit 0
