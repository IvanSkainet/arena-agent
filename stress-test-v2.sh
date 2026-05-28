#!/usr/bin/env bash
# ============================================================
#  Arena Unified Bridge — Stress Test v2
#  Tests: edge cases, error handling, concurrent requests,
#  security, all remaining endpoints, long-running ops
# ============================================================
set -euo pipefail

TOKEN="$(head -1 ~/arena-bridge/token.txt 2>/dev/null || true)"
URL="http://127.0.0.1:8765"
AUTH="Authorization: Bearer $TOKEN"
PASS=0
FAIL=0
SKIP=0

ok()   { PASS=$((PASS+1)); echo -e "\033[32m  PASS\033[0m $1"; }
fail() { FAIL=$((FAIL+1)); echo -e "\033[31m  FAIL\033[0m $1"; }
skip() { SKIP=$((SKIP+1)); echo -e "\033[33m  SKIP\033[0m $1"; }
check(){ echo ""; echo -e "\033[36m>>> $1\033[0m"; }

echo ""
echo "========================================"
echo " Arena Bridge v1.8.4 — Stress Test v2"
echo "========================================"

# ── 1. AUTH & SECURITY ──────────────────────────────────────
check "1.1 No auth → 401 on protected endpoint"
CODE=$(curl -s -o /dev/null -w "%{http_code}" "$URL/v1/sysinfo")
[ "$CODE" = "401" ] && ok "401 without auth" || fail "expected 401, got $CODE"

check "1.2 Bad token → 401"
CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer WRONG_TOKEN" "$URL/v1/sysinfo")
[ "$CODE" = "401" ] && ok "401 with bad token" || fail "expected 401, got $CODE"

check "1.3 X-Arena-Token header (gateway compat)"
R=$(curl -s -H "X-Arena-Token: $TOKEN" "$URL/v1/sysinfo")
echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('ok')==True" 2>/dev/null && ok "X-Arena-Token works" || fail "X-Arena-Token failed"

check "1.4 Public endpoints work without auth"
CODE=$(curl -s -o /dev/null -w "%{http_code}" "$URL/health")
[ "$CODE" = "200" ] && ok "/health public" || fail "/health returned $CODE"
CODE=$(curl -s -o /dev/null -w "%{http_code}" "$URL/v1/version")
[ "$CODE" = "200" ] && ok "/v1/version public" || fail "/v1/version returned $CODE"

# ── 2. EDGE CASES ───────────────────────────────────────────
check "2.1 Empty skill name → 400"
R=$(curl -s -H "$AUTH" -H "Content-Type: application/json" -d '{"name":""}' "$URL/v1/skills/run")
echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('ok')==False and 'missing' in d.get('error','').lower()" 2>/dev/null && ok "empty name → 400" || fail "empty name not handled"

check "2.2 Non-existent skill → error"
R=$(curl -s -H "$AUTH" -H "Content-Type: application/json" -d '{"name":"nonexistent_skill_xyz"}' "$URL/v1/skills/run")
echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('ok')==False" 2>/dev/null && ok "nonexistent skill → error" || fail "nonexistent skill not handled"

check "2.3 Invalid JSON body → 400"
CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "$AUTH" -H "Content-Type: application/json" -d 'not json' "$URL/v1/skills/run")
[ "$CODE" = "400" ] && ok "invalid JSON → 400" || fail "expected 400, got $CODE"

check "2.4 Exec with timeout"
R=$(curl -s -H "$AUTH" -H "Content-Type: application/json" -d '{"cmd":"sleep 0.1 && echo TIMED_OK","timeout":5}' "$URL/v1/exec")
echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('ok')==True and 'TIMED_OK' in d.get('stdout','')" 2>/dev/null && ok "exec with timeout works" || fail "exec timeout failed"

check "2.5 Exec with failing command"
R=$(curl -s -H "$AUTH" -H "Content-Type: application/json" -d '{"cmd":"exit 42","timeout":5}' "$URL/v1/exec")
echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('exit_code')==42" 2>/dev/null && ok "failing exec returns exit code" || fail "failing exec wrong exit code"

# ── 3. ALL REMAINING ENDPOINTS ──────────────────────────────
check "3.1 /v1/hwinfo (hardware inventory)"
R=$(curl -s -H "$AUTH" "$URL/v1/hwinfo")
echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('ok')==True and 'cpu' in json.dumps(d).lower()" 2>/dev/null && ok "hwinfo works" || fail "hwinfo failed"

check "3.2 /v1/ps (process list)"
R=$(curl -s -H "$AUTH" "$URL/v1/ps")
echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin); assert isinstance(d, list) or d.get('ok')==True" 2>/dev/null && ok "ps works" || fail "ps failed"

check "3.3 /v1/config"
R=$(curl -s -H "$AUTH" "$URL/v1/config")
echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin)" 2>/dev/null && ok "config works" || fail "config failed"

check "3.4 /v1/metrics"
R=$(curl -s -H "$AUTH" "$URL/v1/metrics")
echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin)" 2>/dev/null && ok "metrics works" || fail "metrics failed"

check "3.5 /v1/logs"
R=$(curl -s -H "$AUTH" "$URL/v1/logs")
echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin)" 2>/dev/null && ok "logs works" || fail "logs failed"

check "3.6 /v1/audit/stats"
R=$(curl -s -H "$AUTH" "$URL/v1/audit/stats")
echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin); assert 'total' in d" 2>/dev/null && ok "audit stats works" || fail "audit stats failed"

check "3.7 /v1/recall/digest"
R=$(curl -s -H "$AUTH" "$URL/v1/recall/digest")
echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin)" 2>/dev/null && ok "recall digest works" || fail "recall digest failed"

check "3.8 /v1/backups"
R=$(curl -s -H "$AUTH" "$URL/v1/backups")
echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin)" 2>/dev/null && ok "backups works" || fail "backups failed"

check "3.9 /v1/hooks"
R=$(curl -s -H "$AUTH" "$URL/v1/hooks")
echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin)" 2>/dev/null && ok "hooks works" || fail "hooks failed"

check "3.10 /v1/agents"
R=$(curl -s -H "$AUTH" "$URL/v1/agents")
echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin)" 2>/dev/null && ok "agents works" || fail "agents failed"

check "3.11 /v1/subagents"
R=$(curl -s -H "$AUTH" "$URL/v1/subagents")
echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin)" 2>/dev/null && ok "subagents works" || fail "subagents failed"

check "3.12 /v1/inventory"
R=$(curl -s -H "$AUTH" "$URL/v1/inventory")
echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('ok')==True" 2>/dev/null && ok "inventory works" || fail "inventory failed"

check "3.13 /v1/sys/svc"
R=$(curl -s -H "$AUTH" "$URL/v1/sys/svc")
echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin)" 2>/dev/null && ok "sys/svc works" || fail "sys/svc failed"

check "3.14 /v1/status"
R=$(curl -s -H "$AUTH" "$URL/v1/status")
echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin)" 2>/dev/null && ok "status works" || fail "status failed"

check "3.15 / (index)"
R=$(curl -s "$URL/")
echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('ok')==True" 2>/dev/null && ok "index works" || fail "index failed"

# ── 4. TASK QUEUE ───────────────────────────────────────────
check "4.1 Submit task"
R=$(curl -s -H "$AUTH" -H "Content-Type: application/json" -d '{"cmd":"echo TASK_TEST_OK"}' "$URL/v1/tasks")
TID=$(echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('id',''))" 2>/dev/null)
[ -n "$TID" ] && ok "task submitted: $TID" || fail "task submit failed"

check "4.2 List tasks"
R=$(curl -s -H "$AUTH" "$URL/v1/tasks")
echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('count',0)>=0" 2>/dev/null && ok "tasks listed" || fail "tasks list failed"

check "4.3 Clean tasks"
R=$(curl -s -H "$AUTH" -H "Content-Type: application/json" -X POST "$URL/v1/tasks/clean")
echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin)" 2>/dev/null && ok "tasks cleaned" || fail "tasks clean failed"

# ── 5. BACKUP ──────────────────────────────────────────────
check "5.1 Create backup"
R=$(curl -s -H "$AUTH" -H "Content-Type: application/json" -X POST -d '{"paths":["/home/ivan/arena-bridge/memory"]}' "$URL/v1/backup")
echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('ok')==True" 2>/dev/null && ok "backup created" || fail "backup failed"

# ── 6. CONCURRENT REQUESTS ─────────────────────────────────
check "6.1 10 parallel health checks"
FAILS=0
for i in $(seq 1 10); do
    CODE=$(curl -s -o /dev/null -w "%{http_code}" "$URL/health" &)
done
wait
# Re-check synchronously to confirm bridge didn't crash
CODE=$(curl -s -o /dev/null -w "%{http_code}" "$URL/health")
[ "$CODE" = "200" ] && ok "10 parallel requests: bridge still alive" || fail "bridge died after parallel requests"

check "6.2 5 parallel authenticated requests"
for i in $(seq 1 5); do
    curl -s -H "$AUTH" "$URL/v1/sysinfo" > /dev/null &
done
wait
CODE=$(curl -s -o /dev/null -w "%{http_code}" "$URL/health")
[ "$CODE" = "200" ] && ok "5 parallel auth requests: bridge stable" || fail "bridge unstable after auth load"

# ── 7. BROWSER ENDPOINTS ───────────────────────────────────
check "7.1 /v1/browser/search"
R=$(curl -s -H "$AUTH" "$URL/v1/browser/search?q=test")
echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin)" 2>/dev/null && ok "browser search responds" || fail "browser search failed"

check "7.2 /v1/browser/cdp/status"
R=$(curl -s -H "$AUTH" "$URL/v1/browser/cdp/status")
echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin)" 2>/dev/null && ok "CDP status responds" || fail "CDP status failed"

check "7.3 BrowserAct skill: open"
R=$(curl -s -H "$AUTH" -H "Content-Type: application/json" -d '{"name":"browseract","args":["browsers"]}' "$URL/v1/skills/run")
echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('ok')==True" 2>/dev/null && ok "browseract browsers works" || fail "browseract browsers failed"

# ── 8. SKILL RESOLUTION ────────────────────────────────────
check "8.1 Short name: hello → sandbox/hello"
R=$(curl -s -H "$AUTH" -H "Content-Type: application/json" -d '{"name":"hello"}' "$URL/v1/skills/run")
echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('ok')==True and 'hello' in d.get('stdout','')" 2>/dev/null && ok "hello via short name" || fail "hello short name failed"

check "8.2 Full path: sandbox/hello"
R=$(curl -s -H "$AUTH" -H "Content-Type: application/json" -d '{"name":"sandbox/hello"}' "$URL/v1/skills/run")
echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('ok')==True" 2>/dev/null && ok "sandbox/hello via full path" || fail "sandbox/hello full path failed"

check "8.3 Short name: sys-snapshot"
R=$(curl -s -H "$AUTH" -H "Content-Type: application/json" -d '{"name":"sys-snapshot"}' "$URL/v1/skills/run")
echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('ok')==True" 2>/dev/null && ok "sys-snapshot via short name" || fail "sys-snapshot short name failed"

check "8.4 Skill with input field (BrowserAct pattern)"
R=$(curl -s -H "$AUTH" -H "Content-Type: application/json" -d '{"name":"browseract","input":{"action":"browsers"}}' "$URL/v1/skills/run")
echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('ok')==True" 2>/dev/null && ok "skill with input field" || fail "input field failed"

# ── 9. TAILSCALE & FUNNEL ──────────────────────────────────
check "9.1 Funnel status via API"
R=$(curl -s -H "$AUTH" "$URL/v1/sys/funnel")
echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('ok')==True and 'funnel' in d" 2>/dev/null && ok "funnel API works" || fail "funnel API failed"

check "9.2 Funnel URL extracted"
FUNNEL_URL=$(echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('funnel',{}).get('url',''))" 2>/dev/null)
[ -n "$FUNNEL_URL" ] && ok "funnel URL: $FUNNEL_URL" || fail "funnel URL not found"

# ── 10. GATEWAY & MCP ──────────────────────────────────────
check "10.1 /gateway/tools"
R=$(curl -s -H "$AUTH" "$URL/gateway/tools")
echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin); assert 'tools' in d or d.get('ok')==True" 2>/dev/null && ok "gateway tools" || fail "gateway tools failed"

check "10.2 /gateway index"
R=$(curl -s -H "$AUTH" "$URL/gateway")
echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin)" 2>/dev/null && ok "gateway index" || fail "gateway index failed"

# ── 11. GUI ─────────────────────────────────────────────────
check "11.1 /gui returns HTML"
CODE=$(curl -s -o /dev/null -w "%{http_code}" "$URL/gui")
[ "$CODE" = "200" ] && ok "/gui returns 200" || fail "/gui returned $CODE"

# ── 12. LONG-RUNNING EXEC ──────────────────────────────────
check "12.1 Exec with 2s sleep"
R=$(curl -s -H "$AUTH" -H "Content-Type: application/json" -d '{"cmd":"sleep 2 && echo LONG_OK","timeout":10}' "$URL/v1/exec")
echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('ok')==True and 'LONG_OK' in d.get('stdout','')" 2>/dev/null && ok "long exec (2s) works" || fail "long exec failed"

# ── RESULT ──────────────────────────────────────────────────
echo ""
echo "========================================"
echo " STRESS TEST v2 RESULTS"
echo "========================================"
echo " PASS: $PASS"
echo " FAIL: $FAIL"
echo " SKIP: $SKIP"
echo " TOTAL: $((PASS+FAIL+SKIP))"
echo ""
if [ "$FAIL" -eq 0 ]; then
    echo -e "\033[32m ALL TESTS PASSED — READY FOR RELEASE\033[0m"
else
    echo -e "\033[31m $FAIL TEST(S) FAILED — FIX BEFORE RELEASE\033[0m"
fi
echo ""
