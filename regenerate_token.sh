#!/usr/bin/env bash
# Arena Local Bridge - Token Regeneration Script v1.3.0 (Linux/macOS)
# Regenerates token and restarts bridge automatically
set -euo pipefail

BRIDGE_DIR="$HOME/arena-bridge"
TOKEN_FILE="$BRIDGE_DIR/token.txt"

# Find Python
PYTHON_CMD=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON_CMD="$cmd"
        break
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo "[ERROR] Python not found. Please install Python 3.10+"
    exit 1
fi

echo "============================================================"
echo "  Arena Local Bridge - Token Regeneration v1.3.0"
echo "============================================================"
echo

# Stop the bridge if running
if [[ "$(uname -s)" == "Darwin" ]]; then
    launchctl unload "$HOME/Library/LaunchAgents/com.arena.bridge.plist" 2>/dev/null || true
    sleep 2
elif systemctl --user is-active arena-bridge &>/dev/null; then
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
NEW_TOKEN=$($PYTHON_CMD -c "import base64,secrets;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip('='))")

if [ -z "$NEW_TOKEN" ]; then
    echo "[ERROR] Failed to generate token"
    exit 1
fi

# Save token
echo "[3/4] Saving token to $TOKEN_FILE..."
mkdir -p "$BRIDGE_DIR"
echo "$NEW_TOKEN" > "$TOKEN_FILE"
chmod 600 "$TOKEN_FILE"

echo "[4/4] Token regenerated successfully!"
echo
echo "============================================================"
echo "  Token: $NEW_TOKEN"
echo "  Saved to: $TOKEN_FILE"
echo "============================================================"
echo

# Restart the bridge
if [[ "$(uname -s)" == "Darwin" ]]; then
    echo "Restarting bridge (launchd)..."
    launchctl load "$HOME/Library/LaunchAgents/com.arena.bridge.plist" 2>/dev/null || true
    sleep 3
elif systemctl --user is-enabled arena-bridge &>/dev/null; then
    echo "Restarting bridge (systemd)..."
    systemctl --user start arena-bridge
    sleep 3
    systemctl --user status arena-bridge --no-pager || true
elif [ -f "$BRIDGE_DIR/start_bridge.sh" ]; then
    echo "Restarting bridge via start_bridge.sh..."
    nohup "$BRIDGE_DIR/start_bridge.sh" &>/dev/null &
    sleep 3
fi

# Health check
echo
curl -s http://127.0.0.1:8765/health 2>/dev/null && echo || echo "[WARN] Bridge not responding yet"

echo
echo "Done! Use the new token for API calls:"
echo "  Authorization: Bearer $NEW_TOKEN"
echo
echo "Dashboard: http://127.0.0.1:8765/gui"
