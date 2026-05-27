#!/usr/bin/env bash
# ============================================================
#  Arena Unified Bridge - Universal Installer (Linux/macOS)
#  One file, one directory, one command.
# ============================================================
set -euo pipefail

VERSION="1.8.1"
PORT="${ARENA_PORT:-8765}"
PROFILE="owner-shell"

ok()   { echo "[OK] $*"; }
warn() { echo "[WARN] $*"; }
err()  { echo "[ERROR] $*"; }
info() { echo "[INFO] $*"; }

echo ""
echo "========================================"
echo " Arena Unified Bridge v${VERSION} Installer"
echo "========================================"
echo ""

# --- Resolve install directory (the repo itself) ---
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AGENT_DIR="$SCRIPT_DIR"
BRIDGE_DIR="$SCRIPT_DIR"
TOKEN_FILE="$BRIDGE_DIR/token.txt"

# --- Check Python ---
PY=""
for cand in python3.14 python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then PY="$(command -v "$cand")"; break; fi
done
if [ -z "$PY" ]; then
    err "Python 3.10+ not found. Install it first."
    exit 1
fi
PYVER=$("$PY" --version 2>&1 | cut -d' ' -f2)
ok "Python $PYVER found"

# --- Install dependencies ---
info "Installing Python dependencies..."
"$PY" -m pip install aiohttp psutil --quiet 2>/dev/null || true
ok "Python packages ready"

# --- Create subdirectories ---
info "Creating directory structure..."
for d in "$AGENT_DIR/memory" "$AGENT_DIR/missions" \
         "$AGENT_DIR/queue/inbox" "$AGENT_DIR/queue/running" "$AGENT_DIR/queue/done" "$AGENT_DIR/queue/failed" \
         "$AGENT_DIR/reports" "$AGENT_DIR/logs" "$AGENT_DIR/backups" \
         "$AGENT_DIR/hooks/pre_skill.d" "$AGENT_DIR/hooks/post_skill.d" \
         "$AGENT_DIR/skills" "$AGENT_DIR/subagents" "$AGENT_DIR/mcp" "$AGENT_DIR/projects"; do
    mkdir -p "$d"
done
ok "Directories ready"

# --- Generate or preserve token ---
TOKEN=""
if [ -f "$TOKEN_FILE" ]; then
    TOKEN="$(head -1 "$TOKEN_FILE" | tr -d '[:space:]')"
    if [ ${#TOKEN} -lt 16 ]; then
        TOKEN=""
    fi
fi
if [ -z "$TOKEN" ]; then
    TOKEN="$("$PY" -c "import secrets; print(secrets.token_urlsafe(32))")"
    echo "$TOKEN" > "$TOKEN_FILE"
    chmod 600 "$TOKEN_FILE"
    ok "New token generated"
else
    ok "Existing token preserved"
fi

# --- Check bridge file exists ---
BRIDGE_PY="$BRIDGE_DIR/unified_bridge.py"
if [ ! -f "$BRIDGE_PY" ]; then
    err "unified_bridge.py not found in $BRIDGE_DIR"
    exit 1
fi

# --- Create start script ---
START_SCRIPT="$BRIDGE_DIR/start_bridge.sh"
cat > "$START_SCRIPT" << 'STARTEOF'
#!/usr/bin/env bash
exec python3 -u "$(dirname "$0")/unified_bridge.py" serve \
    --root "$HOME" \
    --profile owner-shell \
    --token-file "$(dirname "$0")/token.txt" \
    --port 8765
STARTEOF
chmod +x "$START_SCRIPT"

# --- Install as system service ---
info "Installing as system service..."
OS="$(uname -s)"

if [ "$OS" = "Linux" ] && command -v systemctl >/dev/null 2>&1; then
    # systemd user service
    SD_DIR="$HOME/.config/systemd/user"
    mkdir -p "$SD_DIR"
    cat > "$SD_DIR/arena-bridge.service" << EOF
[Unit]
Description=Arena Unified Bridge v${VERSION}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=$PY -u "$BRIDGE_PY" serve --root $HOME --profile $PROFILE --token-file "$TOKEN_FILE" --port $PORT
WorkingDirectory="$BRIDGE_DIR"
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable arena-bridge.service
    systemctl --user restart arena-bridge.service
    ok "systemd service installed and started"

elif [ "$OS" = "Darwin" ]; then
    # macOS launchd
    PLIST_DIR="$HOME/Library/LaunchAgents"
    mkdir -p "$PLIST_DIR"
    PLIST="$PLIST_DIR/com.arena.bridge.plist"
    cat > "$PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.arena.bridge</string>
    <key>ProgramArguments</key><array>
        <string>$PY</string>
        <string>-u</string>
        <string>$BRIDGE_PY</string>
        <string>serve</string>
        <string>--root</string><string>$HOME</string>
        <string>--profile</string><string>$PROFILE</string>
        <string>--token-file</string><string>$TOKEN_FILE</string>
        <string>--port</string><string>$PORT</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>$AGENT_DIR/logs/bridge.log</string>
    <key>StandardErrorPath</key><string>$AGENT_DIR/logs/bridge_err.log</string>
</dict>
</plist>
EOF
    launchctl unload "$PLIST" 2>/dev/null || true
    launchctl load "$PLIST" 2>/dev/null
    ok "launchd service installed"

else
    # Generic: nohup
    info "No systemd/launchd detected. Starting with nohup."
    PIDS="$(lsof -ti :"$PORT" 2>/dev/null || true)"
    [ -n "$PIDS" ] && kill $PIDS 2>/dev/null || true
    nohup "$START_SCRIPT" >> "$AGENT_DIR/logs/bridge.log" 2>&1 &
    ok "Bridge started with nohup (won't survive reboot)"
fi

# --- Wait for bridge to come up ---
info "Waiting for bridge to start..."
for i in $(seq 1 20); do
    if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
        ok "Bridge is healthy! v${VERSION}"
        break
    fi
    sleep 1
    if [ "$i" -eq 20 ]; then
        warn "Bridge not responding after 20s. Check: journalctl --user -u arena-bridge -n 50"
    fi
done

# --- Done ---
echo ""
echo "========================================"
echo " INSTALLATION COMPLETE"
echo "========================================"
echo ""
echo " Dashboard:  http://127.0.0.1:$PORT/gui"
echo " Health:     http://127.0.0.1:$PORT/health"
echo " Token file: $TOKEN_FILE"
echo ""
echo " Your token:"
echo "   $TOKEN"
echo ""
if [ "$OS" = "Linux" ]; then
    echo " Manage:"
    echo "   systemctl --user status   arena-bridge"
    echo "   systemctl --user restart  arena-bridge"
    echo "   systemctl --user stop     arena-bridge"
    echo "   journalctl --user -u arena-bridge -f"
elif [ "$OS" = "Darwin" ]; then
    echo " Manage:"
    echo "   launchctl print gui/\$UID/com.arena.bridge"
    echo "   launchctl kickstart -k gui/\$UID/com.arena.bridge"
fi
echo ""
echo " Optional:"
echo "   tailscale funnel --bg $PORT   # expose to internet"
echo ""
