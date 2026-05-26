#!/usr/bin/env bash
# ============================================================
#  Arena Local Agent - Update (Linux/macOS/BSD)
#  Preserves token. Only updates code files.
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARENA_HOME="${ARENA_HOME:-$HOME/arena-agent}"
BRIDGE_HOME="${BRIDGE_HOME:-$HOME/arena-local-bridge}"
ARENA_PORT="${ARENA_PORT:-8765}"

PY=""
for cand in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then PY="$(command -v "$cand")"; break; fi
done
[[ -n "$PY" ]] || { echo "Python not found"; exit 1; }

read_ver() {
    [[ -f "$1" ]] || { echo "missing"; return; }
    "$PY" -c "import re;t=open('$1').read();m=re.search(r'VERSION\s*=\s*[\"\\']([^\"\\']+)', t);print(m.group(1) if m else 'unknown')"
}

OLD_VER="$(read_ver "$BRIDGE_HOME/unified_bridge.py")"
echo "Old bridge version: $OLD_VER"

[[ -f "$SCRIPT_DIR/unified_bridge.py" ]] && cp -f "$SCRIPT_DIR/unified_bridge.py" "$BRIDGE_HOME/unified_bridge.py" && echo "[OK] Updated unified_bridge.py"
if [[ -f "$SCRIPT_DIR/dashboard/index.html" ]]; then
    cp -f "$SCRIPT_DIR/dashboard/index.html" "$ARENA_HOME/dashboard/index.html"
    cp -f "$SCRIPT_DIR/dashboard/index.html" "$BRIDGE_HOME/index.html"
    echo "[OK] Updated dashboard/index.html"
elif [[ -f "$SCRIPT_DIR/index.html" ]]; then
    cp -f "$SCRIPT_DIR/index.html" "$ARENA_HOME/dashboard/index.html"
    cp -f "$SCRIPT_DIR/index.html" "$BRIDGE_HOME/index.html"
    echo "[OK] Updated index.html"
fi
[[ -d "$SCRIPT_DIR/bin"     ]] && cp -rf "$SCRIPT_DIR/bin/."     "$ARENA_HOME/bin/"     && echo "[OK] Updated bin/"
[[ -d "$SCRIPT_DIR/scripts" ]] && cp -rf "$SCRIPT_DIR/scripts/." "$ARENA_HOME/scripts/" && echo "[OK] Updated scripts/"

NEW_VER="$(read_ver "$BRIDGE_HOME/unified_bridge.py")"
echo "New bridge version: $NEW_VER"

# Restart service
if command -v systemctl >/dev/null 2>&1 && systemctl --user list-unit-files arena-bridge.service >/dev/null 2>&1; then
    systemctl --user restart arena-bridge.service
    echo "[OK] systemd: arena-bridge.service restarted"
elif [[ "$(uname -s)" == "Darwin" ]] && [[ -f "$HOME/Library/LaunchAgents/com.arena.bridge.plist" ]]; then
    launchctl unload "$HOME/Library/LaunchAgents/com.arena.bridge.plist"
    launchctl load   "$HOME/Library/LaunchAgents/com.arena.bridge.plist"
    echo "[OK] launchd: com.arena.bridge reloaded"
else
    # Best-effort manual restart
    PIDS="$(lsof -ti :"$ARENA_PORT" 2>/dev/null || true)"
    [[ -n "$PIDS" ]] && kill -9 $PIDS 2>/dev/null || true
    nohup "$BRIDGE_HOME/start_bridge.sh" >/dev/null 2>&1 &
    echo "[OK] Bridge restarted manually"
fi

sleep 2
for i in $(seq 1 15); do
    if curl -fsS "http://127.0.0.1:$ARENA_PORT/health" >/dev/null 2>&1; then
        echo "[OK] Bridge healthy"
        break
    fi
    sleep 1
done

echo
echo "============================================================"
echo "  UPDATE COMPLETE: $OLD_VER -> $NEW_VER"
echo "  Token preserved."
echo "  Dashboard: http://127.0.0.1:$ARENA_PORT/gui"
echo "============================================================"
