#!/usr/bin/env bash
# Legacy *nix entrypoint; delegates to the cross-platform Python wrapper
# so that behaviour is identical on Windows/macOS/Linux.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"

PY="${ARENA_PYTHON:-}"
if [[ -z "$PY" ]]; then
  for candidate in python3.12 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      PY="$candidate"
      break
    fi
  done
fi
if [[ -z "$PY" ]]; then
  echo "python not found on PATH (needed by browseract wrapper)" >&2
  exit 1
fi

exec "$PY" "$DIR/run.py" "$@"
