#!/usr/bin/env bash
# =====================================================================
#  Arena Unified Bridge — start (GNU/Linux, macOS, WSL, *BSD)
#
#  POSIX/bash counterpart to start.bat. Runs the bridge in the
#  foreground so systemd-user / supervisord / a plain tmux pane can own
#  the lifecycle. For background/systemd installs use install.sh instead
#  (it registers a proper unit).
#
#  Environment overrides (all optional):
#    ARENA_PYTHON       python interpreter (default: python3, then python)
#    ARENA_ROOT         --root value (default: $HOME)
#    ARENA_PROFILE      --profile value (default: owner-shell)
#    ARENA_TOKEN_FILE   --token-file value (default: token.txt)
#    ARENA_PORT         --port value (default: 8765)
#    ARENA_EXTRA_ARGS   extra args appended verbatim
# =====================================================================
set -euo pipefail

# cd to script directory (equivalent to start.bat "cd /d %~dp0").
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Pick python.
if [ -n "${ARENA_PYTHON:-}" ]; then
    PY="$ARENA_PYTHON"
elif command -v python3 >/dev/null 2>&1; then
    PY="python3"
elif command -v python >/dev/null 2>&1; then
    PY="python"
else
    echo "start.sh: no python3/python on PATH. Install Python 3.10+ first." >&2
    exit 127
fi

if [ ! -f unified_bridge.py ]; then
    echo "start.sh: unified_bridge.py not found in $SCRIPT_DIR." >&2
    echo "          Run this script from the arena-bridge install directory." >&2
    exit 2
fi

ROOT_VAL="${ARENA_ROOT:-$HOME}"
PROFILE_VAL="${ARENA_PROFILE:-owner-shell}"
TOKEN_FILE_VAL="${ARENA_TOKEN_FILE:-token.txt}"
PORT_VAL="${ARENA_PORT:-8765}"

# shellcheck disable=SC2206  # deliberate word-split of user-supplied extras
EXTRA=(${ARENA_EXTRA_ARGS:-})

exec "$PY" -u unified_bridge.py serve \
    --root "$ROOT_VAL" \
    --profile "$PROFILE_VAL" \
    --token-file "$TOKEN_FILE_VAL" \
    --port "$PORT_VAL" \
    "${EXTRA[@]}"
