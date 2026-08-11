#!/usr/bin/env bash
# =====================================================================
#  Arena Unified Bridge — stop (GNU/Linux, macOS, WSL, *BSD)
# =====================================================================
set -euo pipefail

PORT="${ARENA_PORT:-8765}"
STOPPED=0

echo ""
echo "========================================"
echo " Stopping Arena Unified Bridge..."
echo "========================================"
echo ""

# 1. Stop systemd service
if command -v systemctl >/dev/null 2>&1; then
    for SVC in arena-bridge arena-task-runner arena-local-bridge; do
        if systemctl --user is-active --quiet "$SVC" 2>/dev/null; then
            systemctl --user stop "$SVC" 2>/dev/null || true
            echo " [OK] systemd --user service $SVC stopped"
            STOPPED=1
        fi
    done
fi

# 2. Stop launchd on macOS
if [ "$(uname -s)" = "Darwin" ]; then
    PLIST="$HOME/Library/LaunchAgents/com.arena.bridge.plist"
    if [ -f "$PLIST" ]; then
        launchctl unload "$PLIST" 2>/dev/null || true
        echo " [OK] launchd service unloaded"
        STOPPED=1
    fi
fi

# 3. Kill process listening on port 8765
if command -v lsof >/dev/null 2>&1; then
    PIDS="$(lsof -ti -sTCP:LISTEN :"$PORT" 2>/dev/null || true)"
elif command -v fuser >/dev/null 2>&1; then
    PIDS="$(fuser "$PORT"/tcp 2>/dev/null || true)"
else
    PIDS=""
fi
if [ -n "$PIDS" ]; then
    # shellcheck disable=SC2086
    kill $PIDS 2>/dev/null || true
    sleep 1
    if command -v lsof >/dev/null 2>&1; then
        REMAIN="$(lsof -ti -sTCP:LISTEN :"$PORT" 2>/dev/null || true)"
        # shellcheck disable=SC2086
        [ -n "$REMAIN" ] && kill -9 $REMAIN 2>/dev/null || true
    fi
    echo " [OK] Bridge process on port $PORT stopped"
    STOPPED=1
fi

# 4. Stop unified_bridge.py matching processes
if command -v pgrep >/dev/null 2>&1; then
    BPIDS="$(pgrep -f 'unified_bridge.py serve' 2>/dev/null || true)"
    if [ -n "$BPIDS" ]; then
        # shellcheck disable=SC2086
        kill $BPIDS 2>/dev/null || true
        echo " [OK] unified_bridge.py stopped"
        STOPPED=1
    fi
fi

# 5. Stop Tailscale Funnel and Serve
if command -v tailscale >/dev/null 2>&1; then
    tailscale funnel off 2>/dev/null || true
    tailscale serve off 2>/dev/null || true
    echo " [OK] Tailscale funnel and serve turned off"
fi

# 6. Stop orphan cloudflared / ngrok / bore tunnels
if command -v pkill >/dev/null 2>&1; then
    pkill -f 'cloudflared.*tunnel.*127.0.0.1' 2>/dev/null || true
    pkill -f 'bore.*local.*8765' 2>/dev/null || true
    pkill -f 'ngrok.*http.*8765' 2>/dev/null || true
fi

echo ""
echo " [DONE] Arena Bridge and all tunnels fully stopped."
echo ""
