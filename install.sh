#!/usr/bin/env bash
# ============================================================
#  Arena Local Agent - Universal Installer (Linux/macOS/BSD)
#  Cross-distro: Arch, Debian, Ubuntu, Fedora, Alpine, NixOS, macOS, FreeBSD
#  Detects everything dynamically. Asks before regenerating token.
# ============================================================
set -euo pipefail

# Resolve script dir (works on macOS too, no readlink -f needed)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ARENA_HOME="${ARENA_HOME:-$HOME/arena-agent}"
BRIDGE_HOME="${BRIDGE_HOME:-$HOME/arena-local-bridge}"
ARENA_PORT="${ARENA_PORT:-8765}"
ARENA_PROFILE="${ARENA_PROFILE:-owner-shell}"

C_RESET='\033[0m'; C_OK='\033[32m'; C_WARN='\033[33m'; C_ERR='\033[31m'; C_INFO='\033[36m'
ok()   { printf "${C_OK}[OK]${C_RESET} %s\n" "$*"; }
warn() { printf "${C_WARN}[WARN]${C_RESET} %s\n" "$*"; }
err()  { printf "${C_ERR}[ERROR]${C_RESET} %s\n" "$*"; }
info() { printf "${C_INFO}%s${C_RESET}\n" "$*"; }

cat <<EOF
============================================================
  Arena Local Agent - Universal Installer (Unix)
============================================================
  Script dir : $SCRIPT_DIR
  Bridge home: $BRIDGE_HOME
  Agent home : $ARENA_HOME
  Port       : $ARENA_PORT
  Profile    : $ARENA_PROFILE
============================================================
EOF

# === 1. Detect OS + package manager ===
OS_KIND="unknown"
PKG_INSTALL=""
case "$(uname -s)" in
    Linux)
        if   command -v pacman >/dev/null 2>&1; then OS_KIND="arch";   PKG_INSTALL="sudo pacman -S --needed --noconfirm";;
        elif command -v apt-get >/dev/null 2>&1; then OS_KIND="debian"; PKG_INSTALL="sudo apt-get install -y";;
        elif command -v dnf >/dev/null 2>&1; then OS_KIND="fedora"; PKG_INSTALL="sudo dnf install -y";;
        elif command -v apk >/dev/null 2>&1; then OS_KIND="alpine"; PKG_INSTALL="sudo apk add";;
        elif command -v zypper >/dev/null 2>&1; then OS_KIND="suse"; PKG_INSTALL="sudo zypper install -y";;
        elif command -v nix-env >/dev/null 2>&1; then OS_KIND="nixos"; PKG_INSTALL="nix-env -iA";;
        fi
        ;;
    Darwin)
        OS_KIND="macos"
        if command -v brew >/dev/null 2>&1; then PKG_INSTALL="brew install"; fi
        ;;
    FreeBSD)
        OS_KIND="freebsd"; PKG_INSTALL="sudo pkg install -y";;
esac
ok "Detected OS: $OS_KIND"

# === 2. Find Python (3.10+) ===
PY=""
for cand in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then PY="$(command -v "$cand")"; break; fi
done
if [[ -z "$PY" ]]; then
    err "Python 3.10+ not found"
    [[ -n "$PKG_INSTALL" ]] && info "Install: $PKG_INSTALL python3 python3-pip"
    exit 1
fi
PY_VER="$("$PY" -c 'import sys;print(".".join(map(str,sys.version_info[:3])))')"
ok "Python: $PY ($PY_VER)"

# === 3. Create directories ===
mkdir -p "$BRIDGE_HOME" "$ARENA_HOME"/{bin,scripts,dashboard,logs,queue/inbox,memory,missions,reports}
ok "Directories ready"

# === 4. Copy source files (if present in SCRIPT_DIR) ===
copy_if_exists() {
    local src="$1" dst="$2"
    if [[ -e "$src" ]]; then
        cp -rf "$src" "$dst"
        ok "Copied $(basename "$src")"
    fi
}
copy_if_exists "$SCRIPT_DIR/unified_bridge.py" "$BRIDGE_HOME/unified_bridge.py"
if [[ -f "$SCRIPT_DIR/dashboard/index.html" ]]; then
    cp -f "$SCRIPT_DIR/dashboard/index.html" "$ARENA_HOME/dashboard/index.html"
    cp -f "$SCRIPT_DIR/dashboard/index.html" "$BRIDGE_HOME/index.html"
    ok "Copied dashboard/index.html"
elif [[ -f "$SCRIPT_DIR/index.html" ]]; then
    cp -f "$SCRIPT_DIR/index.html" "$ARENA_HOME/dashboard/index.html"
    cp -f "$SCRIPT_DIR/index.html" "$BRIDGE_HOME/index.html"
    ok "Copied index.html"
fi
[[ -d "$SCRIPT_DIR/bin"     ]] && cp -rf "$SCRIPT_DIR/bin/."     "$ARENA_HOME/bin/"     && ok "Copied bin/"
[[ -d "$SCRIPT_DIR/scripts" ]] && cp -rf "$SCRIPT_DIR/scripts/." "$ARENA_HOME/scripts/" && ok "Copied scripts/"

[[ -f "$BRIDGE_HOME/unified_bridge.py" ]] || { err "unified_bridge.py missing"; exit 1; }

# Make bin scripts executable
find "$ARENA_HOME/bin" -type f \( -name "*.sh" -o -name "*.py" -o ! -name "*.*" \) -exec chmod +x {} \; 2>/dev/null || true

# === 5. Detect bridge version dynamically ===
BRIDGE_VERSION="$("$PY" -c "import re;t=open('$BRIDGE_HOME/unified_bridge.py').read();m=re.search(r'VERSION\s*=\s*[\"\\']([^\"\\']+)', t);print(m.group(1) if m else 'unknown')")"
ok "Bridge version: $BRIDGE_VERSION"

# === 6. Install Python dependencies ===
info ""
info "=== Installing Python dependencies ==="
"$PY" -m pip install --user --quiet --upgrade pip 2>/dev/null || true
"$PY" -m pip install --user --quiet aiohttp || "$PY" -m pip install --user aiohttp
ok "Python dependencies ready"

# === 7. Token handling (ASK before regenerating) ===
TOKEN_PATH="$BRIDGE_HOME/token.txt"
REGEN="Y"
if [[ -f "$TOKEN_PATH" ]]; then
    echo
    warn "Existing token found at $TOKEN_PATH"
    read -rp "Regenerate token? Old token will stop working [Y/n]: " ans
    REGEN="${ans:-Y}"
fi
case "$REGEN" in
    [Yy]*|"")
        "$PY" -c "import secrets,base64;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip('='),end='')" > "$TOKEN_PATH"
        chmod 600 "$TOKEN_PATH" 2>/dev/null || true
        ok "New token generated"
        ;;
    *)
        ok "Keeping existing token"
        ;;
esac
ARENA_TOKEN="$(cat "$TOKEN_PATH")"

# === 8. Generate start script ===
cat > "$BRIDGE_HOME/start_bridge.sh" <<EOF
#!/usr/bin/env bash
# Auto-generated by install.sh - DO NOT EDIT
set -e
BRIDGE_DIR="$BRIDGE_HOME"
TOKEN_FILE="\$BRIDGE_DIR/token.txt"
LOG_FILE="$ARENA_HOME/logs/ArenaUnifiedBridge.log"
[[ -f "\$TOKEN_FILE" ]] || { echo "Token file missing"; exit 1; }
TOK="\$(cat "\$TOKEN_FILE" | tr -d '\\n\\r ')"
cd "\$BRIDGE_DIR"
mkdir -p "\$(dirname "\$LOG_FILE")"
exec "$PY" -u unified_bridge.py serve \\
    --root "\$HOME" \\
    --profile "$ARENA_PROFILE" \\
    --token "\$TOK" \\
    --port "$ARENA_PORT" \\
    2>&1 | tee -a "\$LOG_FILE"
EOF
chmod +x "$BRIDGE_HOME/start_bridge.sh"
ok "Wrote start_bridge.sh"

# === 9. systemd / launchd service ===
if [[ "$OS_KIND" != "macos" ]] && command -v systemctl >/dev/null 2>&1; then
    SYSTEMD_DIR="$HOME/.config/systemd/user"
    mkdir -p "$SYSTEMD_DIR"
    cat > "$SYSTEMD_DIR/arena-bridge.service" <<EOF
[Unit]
Description=Arena Local Agent Unified Bridge
After=network.target

[Service]
Type=simple
ExecStart=$BRIDGE_HOME/start_bridge.sh
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable arena-bridge.service >/dev/null 2>&1 || true
    systemctl --user restart arena-bridge.service || systemctl --user start arena-bridge.service
    ok "systemd user service: arena-bridge.service"
elif [[ "$OS_KIND" == "macos" ]]; then
    LA_DIR="$HOME/Library/LaunchAgents"
    mkdir -p "$LA_DIR"
    cat > "$LA_DIR/com.arena.bridge.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.arena.bridge</string>
  <key>ProgramArguments</key>
  <array><string>$BRIDGE_HOME/start_bridge.sh</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$ARENA_HOME/logs/ArenaUnifiedBridge.log</string>
  <key>StandardErrorPath</key><string>$ARENA_HOME/logs/ArenaUnifiedBridge.log</string>
</dict>
</plist>
EOF
    launchctl unload "$LA_DIR/com.arena.bridge.plist" 2>/dev/null || true
    launchctl load "$LA_DIR/com.arena.bridge.plist"
    ok "launchd service: com.arena.bridge"
else
    warn "No systemd/launchd detected. Start bridge manually: $BRIDGE_HOME/start_bridge.sh"
    nohup "$BRIDGE_HOME/start_bridge.sh" >/dev/null 2>&1 &
fi

# === 10. Health check ===
sleep 2
info ""
info "Waiting for bridge..."
for i in $(seq 1 15); do
    if curl -fsS "http://127.0.0.1:$ARENA_PORT/health" >/dev/null 2>&1; then
        ok "Bridge healthy (HTTP 200)"
        break
    fi
    sleep 1
done

cat <<EOF

============================================================
  INSTALLATION COMPLETE
============================================================
  Version    : $BRIDGE_VERSION
  Dashboard  : http://127.0.0.1:$ARENA_PORT/gui
  Health     : http://127.0.0.1:$ARENA_PORT/health
  Token file : $TOKEN_PATH
  Token      : $ARENA_TOKEN
  Log        : $ARENA_HOME/logs/ArenaUnifiedBridge.log

  Manage:
    Start  : $BRIDGE_HOME/start_bridge.sh
$([[ "$OS_KIND" == "macos" ]] && echo "    Service: launchctl {load,unload} ~/Library/LaunchAgents/com.arena.bridge.plist" || echo "    Service: systemctl --user {start,stop,restart,status} arena-bridge")
    Update : ./update.sh (preserves token)
============================================================
EOF
