#!/usr/bin/env bash
# dev/auto-fix — автодиагностика и попытка починить типичные проблемы:
#   - bridge offline → restart
#   - mcp stream/ws offline → restart
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

# 1) Проверяем services
for svc in arena-bridge.service; do
  state=$(systemctl --user is-active "$svc" 2>/dev/null || echo "missing")
  if [[ "$state" != "active" ]]; then
    log "service $svc = $state, restart"
    do_or_dry "systemctl --user restart $svc"
    FIXED=$((FIXED+1))
  fi
done

# 2) Health endpoints
for url in http://127.0.0.1:8765/health http://127.0.0.1:8767/health; do
  if ! curl -sS --max-time 5 "$url" > /dev/null; then
    log "endpoint $url down — restart bridge stack"
    do_or_dry "systemctl --user restart arena-bridge.service"
    FIXED=$((FIXED+1))
    break
  fi
done

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
if ! timeout 5 chromium --version > /dev/null 2>&1; then
  log "WARN: chromium --version выдал ошибку. Используй: agentctl browser sd-shot / py-search"
fi

echo "{\"ok\": true, \"fixed\": $FIXED, \"dry\": $DRY}"
