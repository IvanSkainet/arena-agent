#!/usr/bin/env bash
# dev/auto-fix — автодиагностика и попытка починить типичные проблемы:
#   - bridge offline → restart
#   - ydotoold zombie процессы → kill
#   - старые backup'ы > N штук → prune
#   - chromium падает напрямую → подсказка использовать sd-shot
#
# Usage: agentctl skill run dev/auto-fix [--dry]
set -euo pipefail

DRY=0
[[ "${1:-}" == "--dry" ]] && DRY=1

log() { echo "[auto-fix] $*"; }
do_or_dry() { if [[ $DRY -eq 1 ]]; then log "DRY: $*"; else log "exec: $*"; eval "$@"; fi; }

FIXED=0

# 1) Проверяем bridge service (only if NOT active — never restart self when running)
BRIDGE_SVC="arena-bridge.service"
BRIDGE_STATE=$(systemctl --user is-active "$BRIDGE_SVC" 2>/dev/null || echo "missing")
if [[ "$BRIDGE_STATE" != "active" ]]; then
  log "service $BRIDGE_SVC = $BRIDGE_STATE, restart"
  do_or_dry "systemctl --user restart $BRIDGE_SVC"
  FIXED=$((FIXED+1))
else
  log "service $BRIDGE_SVC = active ✓"
fi

# 2) Health check — only check the main bridge port (8765)
# Do NOT restart the bridge from within itself — just report
if ! curl -sS --max-time 5 "http://127.0.0.1:8765/health" > /dev/null 2>&1; then
  log "WARN: bridge :8765 not responding (but service is active — may be restarting)"
  FIXED=$((FIXED+1))
fi

# 3) Zombie ydotoold не от systemd
ZOMBIES=$(pgrep -af 'ydotoold --socket-path=/run/user/1000/.ydotool_socket' 2>/dev/null | grep -v 'systemd' || true)
if [[ -n "$ZOMBIES" ]]; then
  log "zombie ydotoold processes:"
  echo "$ZOMBIES"
  do_or_dry "pkill -TERM -f 'ydotoold --socket-path=/run/user/1000/.ydotool_socket' || true"
  FIXED=$((FIXED+1))
fi

# 4) Prune backups > 20
BK_DIR="${ARENA_AGENT_HOME:-$HOME/arena-bridge}/backups"
if [[ -d "$BK_DIR" ]]; then
  COUNT=$(ls -1 "$BK_DIR" 2>/dev/null | wc -l)
  if [[ $COUNT -gt 20 ]]; then
    log "$COUNT backups → удаляю старые (оставлю 20)"
    OLD=$(ls -1t "$BK_DIR" | tail -n +21)
    for f in $OLD; do do_or_dry "rm -f '$BK_DIR/$f'"; done
    FIXED=$((FIXED+1))
  fi
fi

# 5) Проверим что chromium хоть как-то отвечает; иначе намекнём
if command -v chromium &>/dev/null; then
  if ! timeout 5 chromium --version > /dev/null 2>&1; then
    log "WARN: chromium --version выдал ошибку. Используй: agentctl browser sd-shot / py-search"
  fi
else
  log "INFO: chromium not found — CDP browser features may be limited"
fi

echo "{\"ok\": true, \"fixed\": $FIXED, \"dry\": $DRY}"
