#!/usr/bin/env bash
echo "[$(date -Iseconds)] post_skill target=$ARENA_TARGET exit=$ARENA_EXIT" >> "$ARENA_AGENT_HOME/logs/hook-trace.log"
