#!/usr/bin/env bash
# clawlab-platform.sh — OS detection and cross-platform helpers for clawlab installers.
# Source from install scripts; do not run directly.
set -Eeuo pipefail

clawlab_platform_init() {
  CLAWLAB_OS="$(uname -s)"
  CLAWLAB_ARCH="$(uname -m)"
  case "$CLAWLAB_OS" in
    Linux)  CLAWLAB_PLATFORM="linux" ;;
    Darwin) CLAWLAB_PLATFORM="macos" ;;
    *)      CLAWLAB_PLATFORM="unknown" ;;
  esac

  if [[ "$CLAWLAB_PLATFORM" == "linux" ]] && command -v apt-get >/dev/null 2>&1; then
    CLAWLAB_PKG="apt"
  elif [[ "$CLAWLAB_PLATFORM" == "macos" ]] && command -v brew >/dev/null 2>&1; then
    CLAWLAB_PKG="brew"
  else
    CLAWLAB_PKG="none"
  fi

  if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
    CLAWLAB_SVC="systemd-user"
  elif [[ "$CLAWLAB_PLATFORM" == "macos" ]]; then
    CLAWLAB_SVC="manual"
  else
    CLAWLAB_SVC="none"
  fi
}

clawlab_repo_root() {
  local here="${1:-${BASH_SOURCE[1]:-${BASH_SOURCE[0]}}}"
  cd "$(dirname "$here")/.." && pwd
}

clawlab_sed_inplace() {
  local expr="$1"; shift
  if [[ "$CLAWLAB_PLATFORM" == "macos" ]]; then
    sed -i '' "$expr" "$@"
  else
    sed -i "$expr" "$@"
  fi
}

clawlab_default_lan_ip() {
  if [[ "$CLAWLAB_PLATFORM" == "macos" ]]; then
    ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "127.0.0.1"
  else
    hostname -I 2>/dev/null | awk '{print $1}'
  fi
}

clawlab_node_major() {
  node -v 2>/dev/null | sed 's/^v//; s/\..*//'
}

clawlab_node_version() {
  node -v 2>/dev/null | sed 's/^v//'
}

# OpenClaw engine: >=22.22.3 <23 || >=24.15.0 <25 || >=25.9.0
CLAWLAB_OPENCLAW_NODE_MAJOR="${CLAWLAB_OPENCLAW_NODE_MAJOR:-24}"

clawlab_node_openclaw_ok() {
  local ver
  ver="$(clawlab_node_version)" || return 1
  [[ -n "$ver" ]] || return 1
  python3 - "$ver" <<'PY'
import sys

def pv(s):
    parts = s.split(".")
    out = []
    for i in range(3):
        chunk = parts[i] if i < len(parts) else "0"
        out.append(int(chunk.split("-")[0]))
    return tuple(out)

v = pv(sys.argv[1])
ok = (
    pv("22.22.3") <= v < pv("23.0.0")
    or pv("24.15.0") <= v < pv("25.0.0")
    or v >= pv("25.9.0")
)
sys.exit(0 if ok else 1)
PY
}

clawlab_openclaw_node_bin_dir() {
  local prefix=""
  case "$CLAWLAB_PKG" in
    brew)
      prefix="$(brew --prefix "node@${CLAWLAB_OPENCLAW_NODE_MAJOR}" 2>/dev/null)" || return 1
      [[ -x "$prefix/bin/node" ]] || return 1
      printf '%s/bin' "$prefix"
      ;;
    *)
      return 1
      ;;
  esac
}

clawlab_prepend_openclaw_node_path() {
  local dir
  dir="$(clawlab_openclaw_node_bin_dir 2>/dev/null)" || return 0
  case ":$PATH:" in
    *":$dir:"*) return 0 ;;
  esac
  export PATH="$dir:$PATH"
  hash -r 2>/dev/null || true
}

clawlab_openclaw_node_requirement_msg() {
  printf '%s' "Node >=22.22.3 <23, >=24.15.0 <25, or >=25.9.0 (recommend brew install node@24)"
}

clawlab_podman_ready() {
  command -v podman >/dev/null 2>&1 || return 1
  if [[ "$CLAWLAB_PLATFORM" == "macos" ]]; then
    podman machine list --format '{{.Name}} {{.Running}}' 2>/dev/null \
      | awk '$2=="true"{found=1} END{exit !found}'
  else
    podman info >/dev/null 2>&1
  fi
}

clawlab_podman_recommend() {
  if [[ "$CLAWLAB_PLATFORM" == "macos" ]]; then
    cat <<'EOF'
  brew install podman
  podman machine init    # once
  podman machine start
EOF
  elif [[ "$CLAWLAB_PKG" == "apt" ]]; then
    cat <<'EOF'
  sudo apt-get install -y podman
  systemctl --user enable --now podman.socket   # rootless, if needed
EOF
  else
    echo "  Install podman from https://podman.io/docs/installation"
  fi
}

clawlab_install_prereqs() {
  local mode="${1:-local}"
  case "$CLAWLAB_PKG" in
    apt)
      sudo apt-get update -qq
      sudo apt-get install -y -qq git curl jq python3 python3-yaml python3-venv build-essential ca-certificates
      if [[ "$mode" == "server" || "$mode" == "local-full" ]]; then
        sudo apt-get install -y -qq nginx libnginx-mod-http-auth-pam openssl 2>/dev/null \
          || sudo apt-get install -y -qq nginx openssl
      fi
      ;;
    brew)
      brew install git curl jq python@3.12 yaml-cpp openssl
      if [[ "$mode" == "server" || "$mode" == "local-full" ]]; then
        brew install nginx lego 2>/dev/null || brew install nginx
      fi
      ;;
    *)
      die "No supported package manager (apt or Homebrew). Install git curl jq python3 manually, then re-run."
      ;;
  esac
}

clawlab_install_node() {
  local want_major="${1:-$CLAWLAB_OPENCLAW_NODE_MAJOR}"

  clawlab_prepend_openclaw_node_path
  if clawlab_node_openclaw_ok; then
    return 0
  fi

  case "$CLAWLAB_PKG" in
    apt)
      curl -fsSL "https://deb.nodesource.com/setup_${want_major}.x" | sudo -E bash -
      sudo apt-get install -y -qq nodejs
      ;;
    brew)
      brew install "node@${want_major}" || die "brew install node@${want_major} failed"
      brew link --overwrite --force "node@${want_major}" 2>/dev/null || true
      clawlab_prepend_openclaw_node_path
      ;;
    *)
      die "Install OpenClaw-compatible Node.js manually ($(clawlab_openclaw_node_requirement_msg)), then re-run."
      ;;
  esac

  clawlab_prepend_openclaw_node_path
  if clawlab_node_openclaw_ok; then
    return 0
  fi
  die "Node $(node -v 2>/dev/null || echo missing) is not supported by OpenClaw ($(clawlab_openclaw_node_requirement_msg))"
}

clawlab_install_pnpm() {
  command -v pnpm >/dev/null 2>&1 && return 0
  command -v node >/dev/null 2>&1 || return 1
  if command -v corepack >/dev/null 2>&1; then
    corepack enable >/dev/null 2>&1 || true
    corepack prepare pnpm@latest --activate
    hash -r 2>/dev/null || true
    command -v pnpm >/dev/null 2>&1 && return 0
  fi
  if command -v npm >/dev/null 2>&1; then
    npm install -g pnpm
    hash -r 2>/dev/null || true
  fi
  command -v pnpm >/dev/null 2>&1
}

clawlab_prepend_uv_path() {
  export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:${PATH}"
  hash -r 2>/dev/null || true
}

clawlab_install_uv() {
  clawlab_prepend_uv_path
  command -v uv >/dev/null 2>&1 && return 0
  case "$CLAWLAB_PKG" in
    brew) brew install uv ;;
    apt)
      curl -fsSL https://astral.sh/uv/install.sh | sh || return 1
      ;;
    *)
      curl -fsSL https://astral.sh/uv/install.sh | sh || return 1
      ;;
  esac
  clawlab_prepend_uv_path
  command -v uv >/dev/null 2>&1
}

clawlab_install_lego() {
  command -v lego >/dev/null && return 0
  local bin="${HOME}/.local/bin"
  mkdir -p "$bin"
  case "$CLAWLAB_PKG" in
    brew) brew install lego ;;
    apt)
      if command -v go >/dev/null; then
        go install github.com/go-acme/lego/v4/cmd/lego@latest
        return 0
      fi
      local asset_key="linux_amd64.tar.gz"
      [[ "$CLAWLAB_ARCH" == "aarch64" || "$CLAWLAB_ARCH" == "arm64" ]] && asset_key="linux_arm64.tar.gz"
      local url
      url="$(curl -fsSL https://api.github.com/repos/go-acme/lego/releases/latest \
        | jq -r --arg k "$asset_key" '.assets[]|select(.name|test($k+"$"))|.browser_download_url' | head -1)"
      [[ -n "$url" ]] || return 1
      curl -fsSL "$url" | tar -xz -C "$bin" lego
      ;;
    *)
      return 1
      ;;
  esac
}

clawlab_server_mode_supported() {
  [[ "$CLAWLAB_PLATFORM" == "linux" && "$CLAWLAB_PKG" == "apt" ]]
}

clawlab_enable_user_units() {
  local unit
  if [[ "$CLAWLAB_SVC" != "systemd-user" ]]; then
    warn "systemd user session not available — start services manually (see preinstall-check.sh)."
    return 1
  fi
  loginctl enable-linger "$USER" >/dev/null 2>&1 || true
  systemctl --user daemon-reload || true
  for unit in "$@"; do
    systemctl --user enable --now "$unit" >/dev/null 2>&1 || warn "could not enable $unit (may not exist yet)"
  done
}

# DefenseClaw judge / Cisco AI Defense defaults (see config-templates/defenseclaw.sample.yaml)
CLAWLAB_JUDGE_OLLAMA_TAG="${CLAWLAB_JUDGE_OLLAMA_TAG:-hf.co/fdtn-ai/Foundation-Sec-8B-Q8_0-GGUF:Q8_0}"
CLAWLAB_JUDGE_DC_MODEL="${CLAWLAB_JUDGE_DC_MODEL:-ollama/hf.co/fdtn-ai/Foundation-Sec-8B-Q8_0-GGUF:Q8_0}"
CLAWLAB_AGENT_OLLAMA_TAG="${CLAWLAB_AGENT_OLLAMA_TAG:-llama3.1:8b}"
CLAWLAB_CISCO_AID_ENDPOINT="${CLAWLAB_CISCO_AID_ENDPOINT:-https://us.api.inspect.aidefense.security.cisco.com}"
CLAWLAB_CISCO_AID_KEY_ENV="${CLAWLAB_CISCO_AID_KEY_ENV:-CISCO_AI_DEFENSE_API_KEY}"

clawlab_ollama_has_model() {
  local tag="$1"
  command -v ollama >/dev/null 2>&1 || return 1
  ollama list 2>/dev/null | awk 'NR>1 {print $1}' | grep -Fxq "$tag"
}

# Approximate pull sizes (GiB) for greenfield disk planning (agent + judge + buffer).
CLAWLAB_OLLAMA_AGENT_SIZE_GIB="${CLAWLAB_OLLAMA_AGENT_SIZE_GIB:-5}"
CLAWLAB_OLLAMA_JUDGE_SIZE_GIB="${CLAWLAB_OLLAMA_JUDGE_SIZE_GIB:-9}"
CLAWLAB_OLLAMA_DISK_BUFFER_GIB="${CLAWLAB_OLLAMA_DISK_BUFFER_GIB:-5}"

clawlab_disk_free_gib() {
  local path="${1:-$HOME}"
  df -g "$path" 2>/dev/null | awk 'NR==2 {print $4}'
}

clawlab_ollama_data_dir_gib() {
  local dir="${1:-$HOME/.ollama}"
  [[ -d "$dir" ]] || return 1
  du -sg "$dir" 2>/dev/null | awk '{print $1}'
}

clawlab_ollama_missing_pull_gib() {
  local need=0
  if ! clawlab_ollama_has_model "$CLAWLAB_AGENT_OLLAMA_TAG" 2>/dev/null; then
    need=$((need + CLAWLAB_OLLAMA_AGENT_SIZE_GIB))
  fi
  if ! clawlab_ollama_has_model "$CLAWLAB_JUDGE_OLLAMA_TAG" 2>/dev/null; then
    need=$((need + CLAWLAB_OLLAMA_JUDGE_SIZE_GIB))
  fi
  echo "$need"
}

clawlab_ollama_required_disk_gib() {
  local missing
  missing="$(clawlab_ollama_missing_pull_gib)"
  echo $((missing + CLAWLAB_OLLAMA_DISK_BUFFER_GIB))
}

clawlab_ensure_ollama_model() {
  local tag="$1"
  command -v ollama >/dev/null 2>&1 || return 1
  if clawlab_ollama_has_model "$tag"; then
    return 0
  fi
  ollama pull "$tag"
}

clawlab_patch_defenseclaw_config() {
  # Usage: clawlab_patch_defenseclaw_config <scanner_mode> <judge_enabled:true|false> [judge_model]
  local scanner_mode="$1" judge_enabled="$2" judge_model="${3:-$CLAWLAB_JUDGE_DC_MODEL}"
  local cfg="${HOME}/.defenseclaw/config.yaml"
  python3 - "$cfg" "$scanner_mode" "$judge_enabled" "$judge_model" \
    "$CLAWLAB_CISCO_AID_ENDPOINT" "$CLAWLAB_CISCO_AID_KEY_ENV" <<'PY'
import sys
from pathlib import Path
try:
    import yaml
except ImportError:
    print("PyYAML not installed — run: pip install pyyaml  (or apt install python3-yaml)", file=sys.stderr)
    sys.exit(2)
cfg_path = Path(sys.argv[1])
scanner_mode, judge_enabled = sys.argv[2], sys.argv[3] == "true"
judge_model, cisco_ep, cisco_env = sys.argv[4], sys.argv[5], sys.argv[6]
d = {}
if cfg_path.exists():
    loaded = yaml.safe_load(cfg_path.read_text())
    d = loaded if isinstance(loaded, dict) else {}
g = d.setdefault("guardrail", {})
g["scanner_mode"] = scanner_mode
g["detection_strategy"] = "regex_judge"
g["detection_strategy_completion"] = "regex_judge"
g.setdefault("judge_sweep", True)
j = g.setdefault("judge", {})
j["enabled"] = judge_enabled
if judge_enabled:
    j["model"] = judge_model
    j["api_base"] = "http://127.0.0.1:11434"
    llm = j.setdefault("llm", {})
    llm["model"] = judge_model
    llm["base_url"] = "http://127.0.0.1:11434"
cad = d.setdefault("cisco_ai_defense", {})
cad["endpoint"] = cisco_ep
cad["api_key_env"] = cisco_env
cad.setdefault("timeout_ms", 3000)
cfg_path.parent.mkdir(parents=True, exist_ok=True)
cfg_path.write_text(yaml.dump(d, default_flow_style=False, sort_keys=False))
print("patched", cfg_path, "scanner_mode=", scanner_mode, "judge=", judge_enabled)
PY
}

clawlab_platform_init
