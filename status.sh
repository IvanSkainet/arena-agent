#!/usr/bin/env bash
# =====================================================================
#  Arena Unified Bridge — status (GNU/Linux, macOS, WSL, *BSD)
# =====================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if command -v python3 >/dev/null 2>&1; then
    exec python3 scripts/check_bridge.py "$@"
elif command -v python >/dev/null 2>&1; then
    exec python scripts/check_bridge.py "$@"
else
    PORT_VAL="${ARENA_PORT:-8765}"
    URL="http://127.0.0.1:${PORT_VAL}/health"
    echo ""
    echo " Arena Bridge Status"
    echo " ==================="
    if command -v curl >/dev/null 2>&1; then
        BODY="$(curl -sS --max-time 3 "$URL" 2>/dev/null || true)"
        if [ -n "$BODY" ]; then
            echo " [UP]   $URL"
            echo " $BODY"
            exit 0
        fi
    fi
    echo " [DOWN] $URL not responding"
    exit 1
fi
