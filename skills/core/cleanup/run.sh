#!/usr/bin/env bash
exec "${ARENA_AGENT_HOME:-$HOME/arena-agent}/.venv/bin/python" "${SKILL_DIR}/run.py" "$@"
