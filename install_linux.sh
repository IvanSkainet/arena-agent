#!/usr/bin/env bash
# ============================================================================
# Arena Local Agent - Universal Linux/macOS Installer v1.3.0
# Supports: Arch/CachyOS, Debian/Ubuntu/Mint, Fedora/RHEL/CentOS/Rocky,
#           Gentoo, Alpine, openSUSE/SLES, NixOS, Solus, Void, Clear Linux,
#           macOS (Homebrew), and any other Linux/macOS
# Works with: All AI chats (ChatGPT, Claude, Gemini, Arena.ai, chat.z.ai, etc.)
# ============================================================================
set -euo pipefail

VERSION="1.3.0"
HOME_DIR="$HOME"
BRIDGE_DIR="$HOME_DIR/arena-local-bridge"
AGENT_DIR="$HOME_DIR/arena-agent"
TOKEN_FILE="$BRIDGE_DIR/token.txt"
BIN_DIR="$AGENT_DIR/bin"
LOG_DIR="$AGENT_DIR/logs"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*"; }
info() { echo -e "${CYAN}[INFO]${NC} $*"; }

# ============================================================================
# Detect OS, distro and package manager
# ============================================================================
detect_os() {
    local os="linux"
    if [[ "$(uname -s)" == "Darwin" ]]; then
        os="macos"
    elif [[ "$(uname -s)" == "FreeBSD" ]]; then
        os="freebsd"
    fi
    echo "$os"
}

detect_distro() {
    local os=$(detect_os)

    if [[ "$os" == "macos" ]]; then
        echo "macos"
        return
    fi

    # Check specific release files first
    if [ -f /etc/cachyos-release ]; then echo "cachyos"; return
    elif [ -f /etc/arch-release ]; then echo "arch"; return
    elif [ -f /etc/artix-release ]; then echo "arch"; return
    elif [ -f /etc/manjaro-release ]; then echo "arch"; return
    elif [ -f /etc/endeavouros-release ]; then echo "arch"; return
    elif [ -f /etc/garuda-release ]; then echo "arch"; return
    elif [ -f /etc/debian_version ]; then
        if [ -f /etc/lsb-release ]; then
            . /etc/lsb-release 2>/dev/null
            case "${DISTRIB_ID:-}" in
                LinuxMint|Pop) echo "debian"; return ;;
            esac
        fi
        echo "debian"; return
    elif [ -f /etc/fedora-release ]; then echo "fedora"; return
    elif [ -f /etc/centos-release ] || [ -f /etc/rocky-release ] || [ -f /etc/almalinux-release ]; then echo "fedora"; return
    elif [ -f /etc/gentoo-release ]; then echo "gentoo"; return
    elif [ -f /etc/alpine-release ]; then echo "alpine"; return
    elif [ -f /etc/opensuse-release ] || [ -f /etc/SUSE-brand ]; then echo "opensuse"; return
    elif [ -f /etc/solus-release ]; then echo "solus"; return
    elif [ -f /etc/void-release ]; then echo "void"; return
    elif [ -f /usr/share/clear/version ]; then echo "clear"; return
    fi

    # Check for NixOS
    if command -v nixos-version &>/dev/null || [ -d /nix/store ]; then
        echo "nixos"; return
    fi

    # Fallback: detect by package manager
    if command -v pacman &>/dev/null; then echo "arch"
    elif command -v apt-get &>/dev/null; then echo "debian"
    elif command -v dnf &>/dev/null; then echo "fedora"
    elif command -v yum &>/dev/null; then echo "fedora"
    elif command -v emerge &>/dev/null; then echo "gentoo"
    elif command -v apk &>/dev/null; then echo "alpine"
    elif command -v zypper &>/dev/null; then echo "opensuse"
    elif command -v eopkg &>/dev/null; then echo "solus"
    elif command -v xbps-install &>/dev/null; then echo "void"
    elif command -v swupd &>/dev/null; then echo "clear"
    elif command -v nix-env &>/dev/null; then echo "nixos"
    elif command -v brew &>/dev/null; then echo "macos"
    else echo "unknown"
    fi
}

OS=$(detect_os)
DISTRO=$(detect_distro)
info "Detected OS: $OS, Distro: $DISTRO"

# ============================================================================
# Package install helpers — universal
# ============================================================================
pkg_install() {
    case "$DISTRO" in
        arch|cachyos)
            if command -v paru &>/dev/null; then paru -S --needed --noconfirm "$@"
            elif command -v yay &>/dev/null; then yay -S --needed --noconfirm "$@"
            else sudo pacman -S --needed --noconfirm "$@"
            fi
            ;;
        debian)
            sudo apt-get update -qq 2>/dev/null
            sudo apt-get install -y "$@"
            ;;
        fedora)
            if command -v dnf &>/dev/null; then sudo dnf install -y "$@"
            else sudo yum install -y "$@"
            fi
            ;;
        gentoo)
            sudo emerge --ask n "$@" 2>/dev/null || sudo emerge "$@"
            ;;
        alpine)
            sudo apk add "$@"
            ;;
        opensuse)
            sudo zypper install -y "$@"
            ;;
        nixos)
            warn "NixOS detected. Add packages to configuration.nix or run: nix-env -iA nixos.$1"
            return 0
            ;;
        solus)
            sudo eopkg install -y "$@"
            ;;
        void)
            sudo xbps-install -y "$@"
            ;;
        clear)
            sudo swupd bundle-add "$@"
            ;;
        macos)
            if command -v brew &>/dev/null; then brew install "$@"
            else err "Homebrew not found. Install from https://brew.sh"; return 1
            fi
            ;;
        freebsd)
            sudo pkg install -y "$@"
            ;;
        *)
            err "Unknown distro. Please install manually: $*"
            return 1
            ;;
    esac
}

pkg_check() {
    command -v "$1" &>/dev/null
}

# ============================================================================
# Version check helper
# ============================================================================
check_version() {
    local cmd="$1"
    local current_ver
    current_ver=$($cmd --version 2>/dev/null | head -1 | grep -oP '[\d.]+' | head -1)
    if [ -z "$current_ver" ]; then return 1; fi
    echo "$current_ver"
}

compare_version() {
    # Returns 0 if $1 >= $2, 1 if $1 < $2
    local v1="$1" v2="$2"
    if [ -z "$v1" ] || [ -z "$v2" ]; then return 0; fi
    local IFS=.
    local i ver1=($v1) ver2=($v2)
    for ((i=${#ver1[@]}; i<${#ver2[@]}; i++)); do ver1[i]=0; done
    for ((i=0; i<${#ver1[@]}; i++)); do
        if [[ -z ${ver2[i]} ]]; then ver2[i]=0; fi
        if ((10#${ver1[i]} > 10#${ver2[i]})); then return 0; fi
        if ((10#${ver1[i]} < 10#${ver2[i]})); then return 1; fi
    done
    return 0
}

# ============================================================================
echo "============================================================"
echo -e "  ${BOLD}Arena Local Agent - Universal Installer v$VERSION${NC}"
echo "  OS: $OS | Distro: $DISTRO"
echo "  Works with: ChatGPT, Claude, Gemini, Arena.ai, chat.z.ai..."
echo "============================================================"
echo

# ============================================================================
# 1. Core dependencies
# ============================================================================
info "=== Core Dependencies ==="

# Python 3.10+
PYTHON_CMD=""
if pkg_check python3; then
    PYTHON_CMD="python3"
elif pkg_check python; then
    PYTHON_CMD="python"
fi

if [ -n "$PYTHON_CMD" ]; then
    PY_VER=$($PYTHON_CMD -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>/dev/null || echo "0.0.0")
    PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
    if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 10 ]; then
        ok "Python $PY_VER found"
    else
        warn "Python $PY_VER found, but 3.10+ required. Installing..."
        case "$DISTRO" in
            arch|cachyos) pkg_install python ;;
            debian) pkg_install python3 python3-pip python3-venv ;;
            fedora) pkg_install python3 python3-pip ;;
            gentoo) pkg_install dev-lang/python ;;
            alpine) pkg_install python3 py3-pip ;;
            opensuse) pkg_install python3 python3-pip ;;
            macos) pkg_install python@3.12 ;;
            *) pkg_install python3 ;;
        esac
        PYTHON_CMD="python3"
    fi
else
    info "Installing Python 3..."
    case "$DISTRO" in
        arch|cachyos) pkg_install python ;;
        debian) pkg_install python3 python3-pip python3-venv ;;
        fedora) pkg_install python3 python3-pip ;;
        gentoo) pkg_install dev-lang/python ;;
        alpine) pkg_install python3 py3-pip ;;
        opensuse) pkg_install python3 python3-pip ;;
        macos) pkg_install python@3.12 ;;
        *) pkg_install python3 ;;
    esac
    PYTHON_CMD="python3"
fi

# Node.js 18+
if pkg_check node; then
    NODE_VER=$(node --version 2>/dev/null)
    NODE_VER_NUM=${NODE_VER#v}
    NODE_MAJOR=$(echo "$NODE_VER_NUM" | cut -d. -f1)
    if [ "$NODE_MAJOR" -lt 18 ]; then
        warn "Node.js $NODE_VER found but 18+ recommended. Updating..."
        case "$DISTRO" in
            debian)
                curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash - 2>/dev/null || true
                sudo apt-get install -y nodejs
                ;;
            macos) brew upgrade node ;;
            *) pkg_install nodejs npm ;;
        esac
    else
        ok "Node.js $NODE_VER found"
    fi
else
    info "Installing Node.js..."
    case "$DISTRO" in
        arch|cachyos) pkg_install nodejs npm ;;
        debian)
            if ! pkg_check curl; then pkg_install curl; fi
            curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash - 2>/dev/null || true
            sudo apt-get install -y nodejs
            ;;
        fedora) pkg_install nodejs npm ;;
        gentoo) pkg_install net-libs/nodejs ;;
        alpine) pkg_install nodejs npm ;;
        opensuse) pkg_install nodejs npm ;;
        macos) pkg_install node ;;
        *) pkg_install nodejs npm ;;
    esac
fi

# Git (with version check)
if pkg_check git; then
    GIT_VER=$(git --version 2>/dev/null | grep -oP '[\d.]+')
    ok "Git $GIT_VER found"
    # Check for update
    info "Checking for Git update..."
    case "$DISTRO" in
        macos) brew upgrade git 2>/dev/null || true ;;
        *) sudo $(which git) update-git-for-windows 2>/dev/null || true ;;
    esac
else
    info "Installing Git..."
    pkg_install git
fi

# curl (required for health checks and API calls)
if ! pkg_check curl; then
    info "Installing curl..."
    pkg_install curl
fi

# pip/aiohttp (with version check)
info "Installing/Updating Python packages..."
AIOHTTP_VER=$($PYTHON_CMD -c "import aiohttp; print(aiohttp.__version__)" 2>/dev/null || echo "not installed")
$PYTHON_CMD -m pip install --user --quiet --upgrade aiohttp 2>/dev/null || \
    pip3 install --user --quiet --upgrade aiohttp 2>/dev/null || \
    pkg_install python3-aiohttp 2>/dev/null || warn "Could not install aiohttp automatically"
AIOHTTP_NEW=$($PYTHON_CMD -c "import aiohttp; print(aiohttp.__version__)" 2>/dev/null || echo "?")
if [ "$AIOHTTP_VER" != "$AIOHTTP_NEW" ] && [ "$AIOHTTP_VER" != "not installed" ]; then
    ok "aiohttp updated: $AIOHTTP_VER -> $AIOHTTP_NEW"
else
    ok "Python packages ready (aiohttp $AIOHTTP_NEW)"
fi

# ============================================================================
# 2. Project structure
# ============================================================================
info "=== Project Structure ==="

mkdir -p "$BRIDGE_DIR" "$BIN_DIR" "$LOG_DIR" "$AGENT_DIR/memory" \
    "$AGENT_DIR/queue/inbox" "$AGENT_DIR/queue/running" "$AGENT_DIR/queue/done" \
    "$AGENT_DIR/queue/failed" "$AGENT_DIR/tools" "$AGENT_DIR/reports/shots"

# Copy/update bridge code
if [ -f "$(dirname "$0")/unified_bridge.py" ]; then
    cp "$(dirname "$0")/unified_bridge.py" "$BRIDGE_DIR/unified_bridge.py"
    ok "unified_bridge.py copied to $BRIDGE_DIR"
elif [ -d "$BRIDGE_DIR/.git" ]; then
    ok "Bridge repo exists, pulling updates..."
    cd "$BRIDGE_DIR" && git pull --ff-only 2>/dev/null || warn "Could not pull updates"
elif [ -f "$BRIDGE_DIR/unified_bridge.py" ]; then
    ok "unified_bridge.py already in $BRIDGE_DIR"
else
    info "Bridge code not found. Please clone or copy the arena-local-bridge repo."
    info "  git clone https://github.com/YOUR_USER/arena-local-bridge.git $BRIDGE_DIR"
fi

# ============================================================================
# 3. Token — AUTO-REGENERATE on every install run
# ============================================================================
info "=== Auth Token (auto-regenerating) ==="

NEW_TOKEN=$($PYTHON_CMD -c "import base64,secrets;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip('='))")
if [ -z "$NEW_TOKEN" ]; then
    # Fallback: keep existing token if generation fails
    if [ -f "$TOKEN_FILE" ]; then
        EXISTING=$(cat "$TOKEN_FILE" | tr -d '[:space:]')
        if [ ${#EXISTING} -ge 16 ]; then
            warn "Token generation failed, keeping existing token"
            NEW_TOKEN="$EXISTING"
        fi
    fi
    if [ -z "$NEW_TOKEN" ]; then
        err "Failed to generate token"
        exit 1
    fi
else
    echo "$NEW_TOKEN" > "$TOKEN_FILE"
    chmod 600 "$TOKEN_FILE"
    ok "New token generated and saved to $TOKEN_FILE"
fi

# ============================================================================
# 4. Optional: Tailscale (with version check)
# ============================================================================
info "=== Optional: Tailscale (VPN/Funnel) ==="

if pkg_check tailscale; then
    TS_VER=$(tailscale version 2>/dev/null | head -1)
    ok "Tailscale $TS_VER found"
    if tailscale status &>/dev/null; then
        ok "Tailscale is active"
    else
        warn "Tailscale installed but not logged in. Run: sudo tailscale up"
    fi
else
    read -p "Install Tailscale? [y/N]: " install_ts
    if [[ "$install_ts" =~ ^[Yy]$ ]]; then
        info "Installing Tailscale..."
        curl -fsSL https://tailscale.com/install.sh | sh 2>/dev/null || warn "Tailscale install failed"
        ok "Tailscale installed. Run: sudo tailscale up"
    else
        info "Skipping Tailscale"
    fi
fi

# ============================================================================
# 5. Optional: Browser (Chromium for headless automation) with version check
# ============================================================================
info "=== Optional: Browser Automation ==="

BROWSER_FOUND=""
if command -v chromium &>/dev/null; then BROWSER_FOUND="chromium"
elif command -v chromium-browser &>/dev/null; then BROWSER_FOUND="chromium-browser"
elif command -v google-chrome &>/dev/null; then BROWSER_FOUND="google-chrome"
elif command -v google-chrome-stable &>/dev/null; then BROWSER_FOUND="google-chrome-stable"
elif command -v firefox &>/dev/null; then BROWSER_FOUND="firefox"
fi

if [ -n "$BROWSER_FOUND" ]; then
    BROWSER_VER=$($BROWSER_FOUND --version 2>/dev/null | head -1 || echo "installed")
    ok "$BROWSER_FOUND found: $BROWSER_VER"
else
    read -p "Install Chromium for headless browser automation? [y/N]: " install_chrome
    if [[ "$install_chrome" =~ ^[Yy]$ ]]; then
        case "$DISTRO" in
            arch|cachyos) pkg_install chromium ;;
            debian) pkg_install chromium-browser 2>/dev/null || pkg_install chromium ;;
            fedora) pkg_install chromium ;;
            gentoo) pkg_install www-client/chromium ;;
            alpine) pkg_install chromium ;;
            opensuse) pkg_install chromium ;;
            macos) pkg_install chromium ;;
            *) warn "Please install Chromium manually" ;;
        esac
    fi
fi

# ============================================================================
# 6. Optional: BrowserAct (AI Browser Automation) with version check
# ============================================================================
info "=== Optional: BrowserAct ==="

if command -v browser-act &>/dev/null; then
    BA_VER_BEFORE=$(browser-act --version 2>/dev/null || echo "installed")
    ok "BrowserAct CLI found: $BA_VER_BEFORE"
    info "Checking for BrowserAct update..."
    npm update -g @anthropic-ai/browser-act 2>/dev/null || true
    npm update -g browser-act 2>/dev/null || true
    BA_VER_AFTER=$(browser-act --version 2>/dev/null || echo "installed")
    if [ "$BA_VER_BEFORE" != "$BA_VER_AFTER" ]; then
        ok "BrowserAct updated: $BA_VER_BEFORE -> $BA_VER_AFTER"
    else
        ok "BrowserAct is up to date ($BA_VER_AFTER)"
    fi
else
    read -p "Install BrowserAct CLI? [y/N]: " install_ba
    if [[ "$install_ba" =~ ^[Yy]$ ]]; then
        info "Installing BrowserAct..."
        npm install -g @anthropic-ai/browser-act 2>/dev/null || \
        npm install -g browser-act 2>/dev/null || warn "BrowserAct install failed"
        if command -v browser-act &>/dev/null; then
            ok "BrowserAct installed: $(browser-act --version 2>/dev/null)"
        else
            warn "BrowserAct installation failed. Try: npm install -g @anthropic-ai/browser-act"
        fi
    fi
fi

# ============================================================================
# 7. Optional: Superpowers (AI Agent Skills from obra/superpowers)
# ============================================================================
info "=== Optional: Superpowers ==="

SP_DIR="$AGENT_DIR/tools/superpowers"
if [ -d "$SP_DIR/.git" ]; then
    SP_BEFORE=$(git -C "$SP_DIR" log -1 --format="%h" 2>/dev/null || echo "?")
    ok "Superpowers found, updating..."
    git -C "$SP_DIR" pull --ff-only 2>/dev/null || warn "Could not update superpowers"
    SP_AFTER=$(git -C "$SP_DIR" log -1 --format="%h" 2>/dev/null || echo "?")
    if [ "$SP_BEFORE" != "$SP_AFTER" ]; then
        ok "Superpowers updated: $SP_BEFORE -> $SP_AFTER"
    else
        ok "Superpowers is up to date ($SP_AFTER)"
    fi
else
    read -p "Install Superpowers (obra/superpowers)? [y/N]: " install_sp
    if [[ "$install_sp" =~ ^[Yy]$ ]]; then
        info "Cloning obra/superpowers..."
        git clone https://github.com/obra/superpowers.git "$SP_DIR" 2>/dev/null || warn "Could not clone superpowers"
        if [ -d "$SP_DIR" ]; then
            ok "Superpowers installed to $SP_DIR"
        fi
    fi
fi

# ============================================================================
# 8. Optional: Dev tools (with version check)
# ============================================================================
info "=== Optional: Dev Tools ==="

DEV_TOOLS_NEEDED=()
for tool in 7z htop jq curl; do
    if ! pkg_check "$tool"; then
        case "$tool" in
            7z) DEV_TOOLS_NEEDED+=(p7zip) ;;
            *) DEV_TOOLS_NEEDED+=($tool) ;;
        esac
    else
        # Version check for existing tools
        TOOL_VER=$($tool --version 2>/dev/null | head -1 || echo "installed")
        ok "$tool found: $TOOL_VER"
    fi
done

if [ ${#DEV_TOOLS_NEEDED[@]} -gt 0 ]; then
    read -p "Install missing dev tools (${DEV_TOOLS_NEEDED[*]})? [y/N]: " install_dev
    if [[ "$install_dev" =~ ^[Yy]$ ]]; then
        pkg_install "${DEV_TOOLS_NEEDED[@]}" 2>/dev/null || warn "Some dev tools could not be installed"
    fi
else
    ok "All dev tools present"
fi

# ============================================================================
# 9. Create agentctl wrapper
# ============================================================================
info "=== agentctl wrapper ==="

if [ ! -f "$BIN_DIR/agentctl" ]; then
    mkdir -p "$BIN_DIR"
    cat > "$BIN_DIR/agentctl" << 'AGENTCTL_EOF'
#!/usr/bin/env bash
# Arena Agent Control CLI
exec python3 "$(dirname "$0")/../arena-local-bridge/unified_bridge.py" "$@"
AGENTCTL_EOF
    chmod +x "$BIN_DIR/agentctl"
fi
ok "agentctl wrapper created"

# ============================================================================
# 10. Create start script (reads token from file, auto-generates if missing)
# ============================================================================
info "=== Start Script ==="

cat > "$BRIDGE_DIR/start_bridge.sh" << START_EOF
#!/usr/bin/env bash
# Arena Unified Bridge startup script v$VERSION
# Reads token from file, auto-generates if missing

TOKEN_FILE="$TOKEN_FILE"
BRIDGE_DIR="$BRIDGE_DIR"
HOME_DIR="$HOME_DIR"
PYTHON_CMD="$PYTHON_CMD"

# Read token from file
TOKEN=\$(cat "\$TOKEN_FILE" 2>/dev/null | tr -d '[:space:]')

# Auto-generate if missing
if [ -z "\$TOKEN" ] || [ \${#TOKEN} -lt 16 ]; then
    echo "[WARN] Token missing or too short, regenerating..."
    TOKEN=\$(\$PYTHON_CMD -c "import base64,secrets;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip('='))")
    if [ -n "\$TOKEN" ]; then
        echo "\$TOKEN" > "\$TOKEN_FILE"
        chmod 600 "\$TOKEN_FILE"
        echo "[OK] New token generated"
    else
        echo "[ERROR] Failed to generate token"
        exit 1
    fi
fi

exec \$PYTHON_CMD "\$BRIDGE_DIR/unified_bridge.py" serve --root "\$HOME_DIR" --profile owner-shell --token "\$TOKEN"
START_EOF
chmod +x "$BRIDGE_DIR/start_bridge.sh"
ok "Start script created"

# ============================================================================
# 11. Create regenerate_token.sh
# ============================================================================
cat > "$BRIDGE_DIR/regenerate_token.sh" << REGEN_EOF
#!/usr/bin/env bash
# Arena Local Bridge - Token Regeneration Script v$VERSION
set -euo pipefail

BRIDGE_DIR="$BRIDGE_DIR"
TOKEN_FILE="$TOKEN_FILE"
PYTHON_CMD="$PYTHON_CMD"

echo "============================================================"
echo "  Arena Local Bridge - Token Regeneration v$VERSION"
echo "============================================================"
echo

# Stop the bridge if running
if systemctl --user is-active arena-bridge &>/dev/null; then
    echo "[1/4] Stopping bridge (systemd)..."
    systemctl --user stop arena-bridge
    sleep 2
elif pgrep -f "unified_bridge.py serve" &>/dev/null; then
    echo "[1/4] Stopping bridge (process)..."
    pkill -f "unified_bridge.py serve" 2>/dev/null || true
    sleep 2
else
    echo "[1/4] Bridge not running, skipping stop."
fi

# Generate new token
echo "[2/4] Generating new token..."
NEW_TOKEN=\$(\$PYTHON_CMD -c "import base64,secrets;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip('='))")

if [ -z "\$NEW_TOKEN" ]; then
    echo "[ERROR] Failed to generate token"
    exit 1
fi

# Save token
echo "[3/4] Saving token to \$TOKEN_FILE..."
mkdir -p "\$(dirname \$TOKEN_FILE)"
echo "\$NEW_TOKEN" > "\$TOKEN_FILE"
chmod 600 "\$TOKEN_FILE"

echo "[4/4] Token regenerated successfully!"
echo
echo "============================================================"
echo "  Token: \$NEW_TOKEN"
echo "  Saved to: \$TOKEN_FILE"
echo "============================================================"
echo

# Restart the bridge
if systemctl --user is-enabled arena-bridge &>/dev/null; then
    echo "Restarting bridge (systemd)..."
    systemctl --user start arena-bridge
    sleep 3
    systemctl --user status arena-bridge --no-pager || true
elif [ -f "\$BRIDGE_DIR/start_bridge.sh" ]; then
    echo "Restarting bridge via start_bridge.sh..."
    nohup "\$BRIDGE_DIR/start_bridge.sh" &>/dev/null &
    sleep 3
fi

# Health check
echo
curl -s http://127.0.0.1:8765/health 2>/dev/null && echo || echo "[WARN] Bridge not responding yet"
echo
echo "Done! Use the new token for API calls:"
echo "  Authorization: Bearer \$NEW_TOKEN"
REGEN_EOF
chmod +x "$BRIDGE_DIR/regenerate_token.sh"
ok "Token regeneration script created"

# ============================================================================
# 12. Systemd user service (if systemd available) or launchd (macOS)
# ============================================================================
if [[ "$OS" == "macos" ]]; then
    # macOS: create launchd plist
    info "=== macOS LaunchAgent ==="
    mkdir -p "$HOME_DIR/Library/LaunchAgents"

    cat > "$HOME_DIR/Library/LaunchAgents/com.arena.bridge.plist" << PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.arena.bridge</string>
    <key>ProgramArguments</key>
    <array>
        <string>$BRIDGE_DIR/start_bridge.sh</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/ArenaUnifiedBridge.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/ArenaUnifiedBridge.err</string>
    <key>WorkingDirectory</key>
    <string>$BRIDGE_DIR</string>
</dict>
</plist>
PLIST_EOF

    launchctl load "$HOME_DIR/Library/LaunchAgents/com.arena.bridge.plist" 2>/dev/null || true
    ok "macOS LaunchAgent created"
    info "Enable with: launchctl load ~/Library/LaunchAgents/com.arena.bridge.plist"

elif command -v systemctl &>/dev/null; then
    # Linux with systemd
    info "=== Systemd User Service ==="
    mkdir -p "$HOME_DIR/.config/systemd/user"

    cat > "$HOME_DIR/.config/systemd/user/arena-bridge.service" << SYSTEMD_EOF
[Unit]
Description=Arena Unified Bridge v$VERSION
After=network.target

[Service]
Type=simple
ExecStart=$BRIDGE_DIR/start_bridge.sh
Restart=on-failure
RestartSec=5
Environment=PATH=/usr/local/bin:/usr/bin:/bin:$HOME_DIR/.local/bin:$HOME_DIR/.cargo/bin
WorkingDirectory=$BRIDGE_DIR

[Install]
WantedBy=default.target
SYSTEMD_EOF

    systemctl --user daemon-reload 2>/dev/null || true
    ok "Systemd user service created"
    info "Enable with: systemctl --user enable --now arena-bridge"
else
    # No systemd, no launchd — use cron or manual
    info "=== No service manager found ==="
    warn "Neither systemd nor launchd found."
    info "You can start the bridge manually: $BRIDGE_DIR/start_bridge.sh"
    info "Or add to crontab: @reboot $BRIDGE_DIR/start_bridge.sh"

    # Try to add to crontab
    read -p "Add to crontab for auto-start? [y/N]: " add_cron
    if [[ "$add_cron" =~ ^[Yy]$ ]]; then
        (crontab -l 2>/dev/null | grep -v "start_bridge.sh"; echo "@reboot $BRIDGE_DIR/start_bridge.sh") | crontab -
        ok "Added to crontab"
    fi
fi

# ============================================================================
# 13. Start the bridge
# ============================================================================
info "=== Starting Bridge ==="

if [[ "$OS" == "macos" ]]; then
    launchctl kickstart -k "gui/$(id -u)/com.arena.bridge" 2>/dev/null || \
    launchctl start com.arena.bridge 2>/dev/null || \
    nohup "$BRIDGE_DIR/start_bridge.sh" &>/dev/null &
    sleep 3
elif command -v systemctl &>/dev/null; then
    systemctl --user enable --now arena-bridge 2>/dev/null || true
    sleep 3
    if systemctl --user is-active arena-bridge &>/dev/null; then
        ok "Bridge started via systemd"
    else
        warn "Systemd start failed, trying direct..."
        nohup "$BRIDGE_DIR/start_bridge.sh" &>/dev/null &
        sleep 3
    fi
else
    nohup "$BRIDGE_DIR/start_bridge.sh" &>/dev/null &
    sleep 3
fi

# Health check
for i in 1 2 3 4 5; do
    if curl -s http://127.0.0.1:8765/health 2>/dev/null | grep -q "ok"; then
        BRIDGE_VER=$(curl -s http://127.0.0.1:8765/health 2>/dev/null | $PYTHON_CMD -c "import sys,json; print(json.load(sys.stdin).get('version','?'))" 2>/dev/null || echo "?")
        ok "Bridge is healthy! v$BRIDGE_VER"
        break
    fi
    [ "$i" -lt 5 ] && sleep 2
done

# ============================================================================
# Summary
# ============================================================================
echo
echo "============================================================"
echo -e "  ${GREEN}${BOLD}ARENA LOCAL AGENT - INSTALLATION COMPLETE!${NC}"
echo "============================================================"
echo
echo "  Dashboard:   http://127.0.0.1:8765/gui"
echo "  Health:      http://127.0.0.1:8765/health"
echo "  Token:       $TOKEN_FILE (auto-regenerated)"
echo "  Log:         $LOG_DIR/"
echo
if [[ "$OS" == "macos" ]]; then
echo "  Auto-start:  launchctl load ~/Library/LaunchAgents/com.arena.bridge.plist"
echo "  Stop:        launchctl unload ~/Library/LaunchAgents/com.arena.bridge.plist"
echo "  Start:       launchctl load ~/Library/LaunchAgents/com.arena.bridge.plist"
echo "  Status:      launchctl list | grep arena"
else
echo "  Auto-start:  systemctl --user enable arena-bridge"
echo "  Stop:        systemctl --user stop arena-bridge"
echo "  Start:       systemctl --user start arena-bridge"
echo "  Status:      systemctl --user status arena-bridge"
fi
echo
echo "  Regen token: $BRIDGE_DIR/regenerate_token.sh"
echo "  BrowserAct:  browser-act --version"
echo "  Superpowers: $SP_DIR"
echo "  Cross-platform: Also available for Windows (install.bat)"
echo
echo "  Compatible with: ChatGPT, Claude, Gemini, Arena.ai, chat.z.ai, any AI"
echo "============================================================"
