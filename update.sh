#!/usr/bin/env bash
# ============================================================
#  Arena Unified Bridge - Update (Linux/macOS/Windows Git Bash)
#  Preserves token. Updates code from git. Restarts service.
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARENA_PORT="${ARENA_PORT:-8765}"

echo "============================================================"
echo "  Arena Bridge - Update"
echo "============================================================"

# Find Python
PY=""
for cand in python3.14 python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then PY="$(command -v "$cand")"; break; fi
done
[[ -n "$PY" ]] || { echo "[ERROR] Python not found"; exit 1; }

# Read old version
OLD_VER="missing"
if [[ -f "$SCRIPT_DIR/unified_bridge.py" ]]; then
    OLD_VER="$("$PY" -c "import re;t=open('$SCRIPT_DIR/unified_bridge.py').read();m=re.search(r'VERSION\s*=\s*[\"\\']([^\"\\']+)', t);print(m.group(1) if m else 'unknown')" 2>/dev/null || echo "unknown")"
fi
echo "Current version: $OLD_VER"

# Pull latest from git
echo "[INFO] Pulling latest from git..."
(cd "$SCRIPT_DIR" && git pull --ff-only 2>/dev/null) || {
    echo "[WARN] git pull failed. Using local files as-is."
}

# Install any new dependencies
echo "[INFO] Checking Python dependencies..."
"$PY" -m pip install aiohttp psutil --quiet 2>/dev/null || true

# Read new version
NEW_VER="missing"
if [[ -f "$SCRIPT_DIR/unified_bridge.py" ]]; then
    NEW_VER="$("$PY" -c "import re;t=open('$SCRIPT_DIR/unified_bridge.py').read();m=re.search(r'VERSION\s*=\s*[\"\\']([^\"\\']+)', t);print(m.group(1) if m else 'unknown')" 2>/dev/null || echo "unknown")"
fi
echo "New version: $NEW_VER"

# Restart service
echo "[INFO] Restarting bridge..."
if command -v systemctl >/dev/null 2>&1 && systemctl --user list-unit-files arena-bridge.service >/dev/null 2>&1; then
    systemctl --user restart arena-bridge.service
    echo "[OK] systemd: arena-bridge.service restarted"
elif [[ "$(uname -s)" == "Darwin" ]] && [[ -f "$HOME/Library/LaunchAgents/com.arena.bridge.plist" ]]; then
    launchctl unload "$HOME/Library/LaunchAgents/com.arena.bridge.plist" 2>/dev/null || true
    launchctl load "$HOME/Library/LaunchAgents/com.arena.bridge.plist" 2>/dev/null
    echo "[OK] launchd: bridge reloaded"
else
    PIDS="$(lsof -ti :"$ARENA_PORT" 2>/dev/null || true)"
    [[ -n "$PIDS" ]] && kill $PIDS 2>/dev/null || true
    nohup "$SCRIPT_DIR/start_bridge.sh" >/dev/null 2>&1 &
    echo "[OK] Bridge restarted manually"
fi

# Wait for health
sleep 2
for i in $(seq 1 15); do
    if curl -fsS "http://127.0.0.1:$ARENA_PORT/health" >/dev/null 2>&1; then
        echo "[OK] Bridge healthy"
        break
    fi
    sleep 1
done

echo ""
echo "============================================================"
echo "  UPDATE COMPLETE: $OLD_VER -> $NEW_VER"
echo "  Token preserved."
echo "  Dashboard: http://127.0.0.1:$ARENA_PORT/gui"
echo "============================================================"
