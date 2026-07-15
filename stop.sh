#!/usr/bin/env bash
# =====================================================================
#  Arena Unified Bridge — stop (GNU/Linux, macOS, WSL, *BSD)
#
#  Counterpart to stop.bat. Strategy (first match wins):
#    1. systemd --user service `arena-bridge` — stop via systemctl.
#    2. systemd system service `arena-bridge` — stop via sudo systemctl.
#    3. Match `unified_bridge.py serve` by argv and SIGTERM it.
#
#  Exit 0 on any successful stop, 0 also if bridge was not running.
# =====================================================================
set -euo pipefail

STOPPED=0

if command -v systemctl >/dev/null 2>&1; then
    if systemctl --user is-active --quiet arena-bridge 2>/dev/null; then
        echo "stop.sh: stopping systemd --user unit arena-bridge"
        systemctl --user stop arena-bridge
        STOPPED=1
    elif systemctl is-active --quiet arena-bridge 2>/dev/null; then
        echo "stop.sh: stopping systemd system unit arena-bridge (sudo)"
        sudo systemctl stop arena-bridge
        STOPPED=1
    fi
fi

if [ "$STOPPED" -eq 0 ]; then
    # pgrep -f matches the full command line, unlike plain pgrep.
    if command -v pgrep >/dev/null 2>&1; then
        PIDS="$(pgrep -f 'unified_bridge.py serve' || true)"
    else
        # Portable fallback: ps + grep.
        PIDS="$(ps -eo pid,args | awk '/unified_bridge.py serve/ && !/awk/ {print $1}')"
    fi
    if [ -n "$PIDS" ]; then
        echo "stop.sh: sending SIGTERM to: $PIDS"
        # shellcheck disable=SC2086  # PIDS is deliberately word-split
        kill $PIDS
        # Give it 5s to exit cleanly, then SIGKILL survivors.
        for _ in 1 2 3 4 5; do
            sleep 1
            REMAIN=""
            for pid in $PIDS; do
                if kill -0 "$pid" 2>/dev/null; then
                    REMAIN="$REMAIN $pid"
                fi
            done
            [ -z "$REMAIN" ] && break
        done
        if [ -n "${REMAIN:-}" ]; then
            echo "stop.sh: SIGKILL survivors:$REMAIN"
            # shellcheck disable=SC2086
            kill -9 $REMAIN 2>/dev/null || true
        fi
        STOPPED=1
    fi
fi

if [ "$STOPPED" -eq 0 ]; then
    echo "stop.sh: bridge does not appear to be running."
else
    echo "stop.sh: bridge stopped."
fi
