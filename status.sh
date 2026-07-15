#!/usr/bin/env bash
# =====================================================================
#  Arena Unified Bridge — status (GNU/Linux, macOS, WSL, *BSD)
#
#  Counterpart to status.bat. Prints bridge health and process info.
#  Exit code: 0 when /health returns ok, 1 otherwise.
# =====================================================================
set -euo pipefail

PORT_VAL="${ARENA_PORT:-8765}"
URL="http://127.0.0.1:${PORT_VAL}/health"

echo
echo " Arena Bridge Status"
echo " ==================="

# Show any matching processes (informational, not fatal).
if command -v pgrep >/dev/null 2>&1; then
    PIDS="$(pgrep -f 'unified_bridge.py serve' || true)"
    if [ -n "$PIDS" ]; then
        echo " Processes: $PIDS"
    else
        echo " Processes: (none matching 'unified_bridge.py serve')"
    fi
fi

# systemd unit state (best-effort).
if command -v systemctl >/dev/null 2>&1; then
    for scope in "--user" ""; do
        # shellcheck disable=SC2086  # scope is either --user or empty
        state="$(systemctl $scope is-active arena-bridge 2>/dev/null || true)"
        if [ -n "$state" ] && [ "$state" != "inactive" ] && [ "$state" != "unknown" ]; then
            label="user"; [ -z "$scope" ] && label="system"
            echo " systemd ($label): $state"
        fi
    done
fi

# Health probe. Prefer curl, fall back to python.
if command -v curl >/dev/null 2>&1; then
    BODY="$(curl -sS --max-time 3 "$URL" || true)"
elif command -v python3 >/dev/null 2>&1; then
    BODY="$(python3 -c "
import sys, urllib.request
try:
    with urllib.request.urlopen('$URL', timeout=3) as r:
        sys.stdout.write(r.read().decode('utf-8', 'replace'))
except Exception:
    pass
")"
else
    BODY=""
fi

if [ -z "$BODY" ]; then
    echo " [DOWN] $URL not responding"
    exit 1
fi

echo " [UP]   $URL"
echo " $BODY"
exit 0
