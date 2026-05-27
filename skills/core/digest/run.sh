#!/usr/bin/env bash
set -euo pipefail
exec python3 "${SKILL_DIR}/run.py" "$@"
