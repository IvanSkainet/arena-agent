#!/usr/bin/env bash
# Arena Local Agent - Linux Installer v14.2 (Unified Bridge v1.1.0)
# Cross-platform: works on Arch/CachyOS, Debian/Ubuntu, Fedora/RHEL
# 1 process, 1 port, 1 systemd service
#
# Usage:     bash install_linux.sh
# Uninstall: bash install_linux.sh --uninstall
# Update:    bash install_linux.sh --update

set -euo pipefail

BRIDGE_PATH="$HOME/arena-local-bridge"
AGENT_PATH="$HOME/arena-agent"
TOKEN_PATH="$BRIDGE_PATH/token.txt"
LOG_FILE="$AGENT_PATH/logs/ArenaUnifiedBridge.log"
SERVICE_NAME="arena-unified-bridge"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${GREEN}[OK]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }
header() { echo -e "\n${CYAN}=== $1 ===${NC}"; }

# ------------------- Detect Distro -------------------
detect_distro() {
    if [ -f /etc/arch-release ]; then
        echo "arch"
    elif [ -f /etc/cachyos-release ]; then
        echo "cachyos"
    elif [ -f /etc/debian_version ]; then
        echo "debian"
    elif [ -f /etc/fedora-release ]; then
        echo "fedora"
    elif [ -f /etc/redhat-release ]; then
        echo "rhel"
    else
        echo "unknown"
    fi
}

DISTRO=$(detect_distro)
echo -e "${CYAN}==================================================${NC}"
echo -e "${CYAN}  Arena Local Agent - Unified Bridge v1.1.0${NC}"
echo -e "${CYAN}  Linux Installer for $(uname -o)${NC}"
echo -e "${CYAN}  Detected: $DISTRO${NC}"
echo -e "${CYAN}==================================================${NC}"

# ------------------- Uninstall -------------------
if [ "${1:-}" = "--uninstall" ]; then
    header "UNINSTALLING"
    systemctl --user stop "$SERVICE_NAME" 2>/dev/null || true
    systemctl --user disable "$SERVICE_NAME" 2>/dev/null || true
    rm -f "$HOME/.config/systemd/user/$SERVICE_NAME.service"
    systemctl --user daemon-reload 2>/dev/null || true
    info "Uninstalled $SERVICE_NAME"
    exit 0
fi

# ------------------- Update -------------------
if [ "${1:-}" = "--update" ]; then
    header "UPDATING"
    systemctl --user restart "$SERVICE_NAME" 2>/dev/null || true
    sleep 3
    if curl -s http://127.0.0.1:8765/health | grep -q '"ok"'; then
        info "Bridge updated and running!"
    else
        warn "Bridge may not be running. Check: systemctl --user status $SERVICE_NAME"
    fi
    exit 0
fi

# ------------------- Ensure Dependencies -------------------
header "Core Dependencies"

# Python
PY=$(command -v python3 || command -v python || echo "")
if [ -z "$PY" ]; then
    warn "Python not found. Installing..."
    case $DISTRO in
        arch|cachyos) sudo pacman -S --noconfirm python ;;
        debian) sudo apt-get install -y python3 python3-pip ;;
        fedora|rhel) sudo dnf install -y python3 python3-pip ;;
        *) error "Install Python manually: https://www.python.org/"; exit 1 ;;
    esac
    PY=$(command -v python3 || command -v python)
fi
info "Python: $PY ($($PY --version 2>&1))"

# pip
if ! command -v pip3 &>/dev/null && ! command -v pip &>/dev/null; then
    case $DISTRO in
        arch|cachyos) sudo pacman -S --noconfirm python-pip ;;
        debian) sudo apt-get install -y python3-pip ;;
        fedora|rhel) sudo dnf install -y python3-pip ;;
    esac
fi

# Node.js
if ! command -v node &>/dev/null; then
    warn "Node.js not found."
    read -p "Install Node.js LTS? [Y/n] " ans
    if [ "$ans" = "" ] || [ "$ans" = "Y" ] || [ "$ans" = "y" ]; then
        case $DISTRO in
            arch|cachyos) sudo pacman -S --noconfirm nodejs npm ;;
            debian)
                curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
                sudo apt-get install -y nodejs
                ;;
            fedora|rhel)
                curl -fsSL https://rpm.nodesource.com/setup_20.x | sudo bash -
                sudo dnf install -y nodejs
                ;;
        esac
        info "Node.js installed"
    fi
fi

# Python packages
header "Python Packages"
$PY -m pip install --quiet --upgrade aiohttp httpx requests beautifulsoup4 2>/dev/null
info "Python packages ready"

# ------------------- Optional: Git -------------------
if ! command -v git &>/dev/null; then
    warn "Git not found."
    read -p "Install Git? [Y/n] " ans
    if [ "$ans" = "" ] || [ "$ans" = "Y" ] || [ "$ans" = "y" ]; then
        case $DISTRO in
            arch|cachyos) sudo pacman -S --noconfirm git ;;
            debian) sudo apt-get install -y git ;;
            fedora|rhel) sudo dnf install -y git ;;
        esac
        info "Git installed"
    fi
fi

# ------------------- Optional: Tailscale -------------------
if ! command -v tailscale &>/dev/null; then
    warn "Tailscale not found."
    read -p "Install Tailscale for remote access? [Y/n] " ans
    if [ "$ans" = "" ] || [ "$ans" = "Y" ] || [ "$ans" = "y" ]; then
        curl -fsSL https://tailscale.com/install.sh | sh
        info "Tailscale installed. Run: sudo tailscale up"
    fi
fi

# ------------------- Optional: Browser -------------------
header "Browser Automation"
if command -v chromium &>/dev/null || command -v google-chrome &>/dev/null || command -v chromium-browser &>/dev/null; then
    info "Chromium browser available for headless automation"
else
    warn "No Chromium found for browser automation."
    read -p "Install Chromium? [y/N] " ans
    if [ "$ans" = "Y" ] || [ "$ans" = "y" ]; then
        case $DISTRO in
            arch|cachyos) sudo pacman -S --noconfirm chromium ;;
            debian) sudo apt-get install -y chromium-browser ;;
            fedora|rhel) sudo dnf install -y chromium ;;
        esac
    fi
fi

# ------------------- Directories -------------------
header "Directory Structure"
mkdir -p "$BRIDGE_PATH" "$AGENT_PATH"/{scripts,bin,logs,queue/{inbox,running,done,failed},dashboard,memory,reports,skills,hooks}

# ------------------- Token -------------------
header "Access Token"
if [ -f "$TOKEN_PATH" ] && [ "$(wc -c < "$TOKEN_PATH")" -ge 20 ]; then
    info "Using existing token"
    TOKEN=$(cat "$TOKEN_PATH" | tr -d '\n\r' | sed 's/^\xEF\xBB\xBF//')
else
    TOKEN=$(python3 -c "import secrets,string;print(''.join(secrets.choice(string.ascii_letters+string.digits+'-_') for _ in range(43)))")
    echo -n "$TOKEN" > "$TOKEN_PATH"
    chmod 600 "$TOKEN_PATH"
    info "New token generated"
fi

# ------------------- agentctl wrapper -------------------
cat > "$AGENT_PATH/bin/agentctl" << 'AGENTCTL'
#!/usr/bin/env bash
exec python3 "$(dirname "$0")/agentctl" "$@"
AGENTCTL
chmod +x "$AGENT_PATH/bin/agentctl"

# Add to PATH if not present
if [[ ":$PATH:" != *":$AGENT_PATH/bin:"* ]]; then
    echo "export PATH=\"$AGENT_PATH/bin:\$PATH\"" >> "$HOME/.bashrc"
    export PATH="$AGENT_PATH/bin:$PATH"
    info "Added bin to PATH (added to .bashrc)"
fi

# ------------------- systemd User Service -------------------
header "Systemd Service"

mkdir -p "$HOME/.config/systemd/user"

cat > "$HOME/.config/systemd/user/$SERVICE_NAME.service" << SERVICEEOF
[Unit]
Description=Arena Unified Bridge v1.1.0
After=network.target

[Service]
Type=simple
ExecStart=$PY -u $BRIDGE_PATH/unified_bridge.py serve --root "$HOME" --profile owner-shell --token "$TOKEN"
Restart=always
RestartSec=5
StandardOutput=append:$LOG_FILE
StandardError=append:$LOG_FILE
WorkingDirectory=$BRIDGE_PATH

[Install]
WantedBy=default.target
SERVICEEOF

systemctl --user daemon-reload
systemctl --user enable "$SERVICE_NAME"
systemctl --user restart "$SERVICE_NAME" 2>/dev/null || true

info "Systemd service installed and started"

# ------------------- Verify -------------------
header "Verification"
sleep 3

HEALTH=$(curl -s http://127.0.0.1:8765/health 2>/dev/null || echo "")
if echo "$HEALTH" | grep -q '"ok"'; then
    VERSION=$(echo "$HEALTH" | $PY -c "import sys,json;print(json.load(sys.stdin).get('version','?'))" 2>/dev/null || echo "?")
    info "Bridge is healthy! v$VERSION"
else
    warn "Bridge not responding yet. Check: systemctl --user status $SERVICE_NAME"
    warn "Log: $LOG_FILE"
fi

# ------------------- Summary -------------------
echo ""
echo -e "${GREEN}==================================================${NC}"
echo -e "${GREEN}  ARENA LOCAL AGENT - INSTALLATION COMPLETE!${NC}"
echo -e "${GREEN}==================================================${NC}"
echo ""
echo "  Dashboard:  http://127.0.0.1:8765/gui"
echo "  Health:     http://127.0.0.1:8765/health"
echo "  Log:        $LOG_FILE"
echo ""
echo "  Service:    systemctl --user status $SERVICE_NAME"
echo "  Stop:       systemctl --user stop $SERVICE_NAME"
echo "  Start:      systemctl --user start $SERVICE_NAME"
echo "  Logs:       journalctl --user -u $SERVICE_NAME -f"
echo ""
echo -e "  ${CYAN}Cross-platform: also see install_windows_service.ps1${NC}"
echo -e "${GREEN}==================================================${NC}"
