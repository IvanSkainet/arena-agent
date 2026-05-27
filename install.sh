#!/usr/bin/env bash
# ============================================================
#  Arena Unified Bridge v1.7.0 - Universal Installer (Linux/macOS)
# ============================================================
set -e

BRIDGE_DIR="$(cd "$(dirname "$0")" && pwd)"
PORT=8765
PROFILE="owner-shell"

echo ""
echo "  ========================================"
echo "   Arena Unified Bridge v1.7.0 Installer"
echo "  ========================================"
echo ""

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] Python 3 not found. Install Python 3.10+ first."
    exit 1
fi

PYVER=$(python3 --version 2>&1 | cut -d' ' -f2)
echo "[OK] Python $PYVER found"

# Install dependencies
echo ""
echo "[1/5] Installing Python dependencies..."
python3 -m pip install aiohttp psutil --quiet 2>/dev/null || true
echo "      Done."

# Create directories
echo ""
echo "[2/5] Creating directory structure..."
for d in dashboard bin scripts skills tools memory missions hooks logs queue reports backups mcp docs subagents projects; do
    mkdir -p "$BRIDGE_DIR/$d"
done
echo "      Done."

# Generate token
echo ""
echo "[3/5] Generating auth token..."
if [ ! -f "$BRIDGE_DIR/token.txt" ]; then
    python3 -c "import secrets; print(secrets.token_urlsafe(32))" > "$BRIDGE_DIR/token.txt"
    echo "      New token generated."
else
    echo "      Existing token found."
fi

# Install as systemd service (Linux) or launchd (macOS)
echo ""
echo "[4/5] Installing as system service..."
if [ "$(uname)" = "Darwin" ]; then
    # macOS launchd
    PLIST="$HOME/Library/LaunchAgents/com.arena.bridge.plist"
    cat > "$PLIST" << PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.arena.bridge</string>
    <key>ProgramArguments</key><array>
        <string>$(which python3)</string>
        <string>-u</string>
        <string>$BRIDGE_DIR/unified_bridge.py</string>
        <string>serve</string>
        <string>--root</string><string>$HOME</string>
        <string>--profile</string><string>$PROFILE</string>
        <string>--token-file</string><string>$BRIDGE_DIR/token.txt</string>
        <string>--port</string><string>$PORT</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>$BRIDGE_DIR/logs/bridge.log</string>
    <key>StandardErrorPath</key><string>$BRIDGE_DIR/logs/bridge_err.log</string>
</dict>
</plist>
PLISTEOF
    launchctl load "$PLIST" 2>/dev/null || true
    echo "      launchd service installed."
elif [ "$(uname)" = "Linux" ]; then
    # Linux systemd user service
    mkdir -p "$HOME/.config/systemd/user"
    cat > "$HOME/.config/systemd/user/arena-bridge.service" << SVCEOF
[Unit]
Description=Arena Unified Bridge
After=network.target

[Service]
Type=simple
ExecStart=$(which python3) -u $BRIDGE_DIR/unified_bridge.py serve --root $HOME --profile $PROFILE --token-file $BRIDGE_DIR/token.txt --port $PORT
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
SVCEOF
    systemctl --user daemon-reload
    systemctl --user enable arena-bridge
    systemctl --user start arena-bridge
    echo "      systemd service installed."
fi

# Verify
echo ""
echo "[5/5] Verifying..."
sleep 2
if curl -s "http://127.0.0.1:$PORT/health" | grep -q '"ok"'; then
    echo "      Bridge is UP!"
else
    echo "      [WARN] Bridge not responding yet. Check logs."
fi

echo ""
echo "  ========================================"
echo "   Installation Complete!"
echo "  ========================================"
echo ""
echo "  Bridge URL:    http://127.0.0.1:$PORT"
echo "  Dashboard:     http://127.0.0.1:$PORT/gui"
echo "  Token file:    $BRIDGE_DIR/token.txt"
echo ""
if [ -f "$BRIDGE_DIR/token.txt" ]; then
    echo "  Your auth token:"
    echo "  $(cat $BRIDGE_DIR/token.txt)"
    echo ""
fi
