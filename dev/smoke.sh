#!/usr/bin/env bash
# Runtime smoke test for Arena Unified Bridge.
# Boots the bridge on a throwaway port, checks /health, then stops it.
# Used as a fast sanity gate after each refactor step (Phase 2 monolith split).
#
# Usage: bash dev/smoke.sh [PORT]
set -uo pipefail

PORT="${1:-8799}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-python3}"
LOG="$(mktemp)"

cd "$ROOT"
"$PY" unified_bridge.py serve --port "$PORT" --bind 127.0.0.1 >"$LOG" 2>&1 &
PID=$!
trap 'kill "$PID" 2>/dev/null; sleep 1; kill -9 "$PID" 2>/dev/null; rm -f "$LOG"' EXIT

# Wait up to ~10s for the port to answer.
ok=""
for _ in $(seq 1 20); do
    sleep 0.5
    body="$(curl -s --max-time 3 "http://127.0.0.1:$PORT/health" 2>/dev/null || true)"
    if echo "$body" | grep -q '"ok": *true'; then ok="$body"; break; fi
done

if [ -n "$ok" ]; then
    echo "SMOKE OK: $ok"
    exit 0
else
    echo "SMOKE FAILED — /health did not return ok on port $PORT"
    echo "--- server log ---"
    tail -30 "$LOG"
    exit 1
fi
