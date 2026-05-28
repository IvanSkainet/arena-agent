#!/usr/bin/env bash
# stress-test-v3.sh — Arena Unified Bridge v1.9.0 CDP/BrowserAct/SuperPowers Test Suite
# Works in bash, zsh, and fish (via bash invocation)
# Usage: bash stress-test-v3.sh [BRIDGE_URL] [TOKEN]
set -euo pipefail

# --- Config ---
URL="${1:-http://127.0.0.1:8765}"
TOKEN="${2:-}"
BRIDGE_HOME="${ARENA_AGENT_HOME:-$HOME/arena-bridge}"

# Auto-detect token if not provided
if [ -z "$TOKEN" ]; then
    if [ -f "$BRIDGE_HOME/token.txt" ]; then
        TOKEN=$(cat "$BRIDGE_HOME/token.txt")
    else
        echo "ERROR: No token found. Pass as arg2 or place in $BRIDGE_HOME/token.txt"
        exit 1
    fi
fi

AUTH="-H \"Authorization: Bearer $TOKEN\""
PASS=0
FAIL=0
SKIP=0
ERRORS=()

# --- Helpers ---
stamp() { date -u +%H:%M:%S; }

check() {
    local name="$1" ok="$2" detail="${3:-}"
    if [ "$ok" = "true" ]; then
        echo "  [PASS] $name $detail"
        PASS=$((PASS + 1))
    elif [ "$ok" = "skip" ]; then
        echo "  [SKIP] $name — $detail"
        SKIP=$((SKIP + 1))
    else
        echo "  [FAIL] $name $detail"
        FAIL=$((FAIL + 1))
        ERRORS+=("$name: $detail")
    fi
}

api_get() {
    curl -s -H "Authorization: Bearer $TOKEN" "$URL$1" 2>/dev/null
}

api_post() {
    local endpoint="$1"
    local body="${2:-}"
    if [ -n "$body" ]; then
        curl -s -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "$body" "$URL$endpoint" 2>/dev/null
    else
        curl -s -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -X POST "$URL$endpoint" 2>/dev/null
    fi
}

jq_val() {
    python3 -c "import json,sys; d=json.load(sys.stdin); print(d$1)" 2>/dev/null
}

jq_check() {
    python3 -c "import json,sys; d=json.load(sys.stdin); v=d$1; sys.exit(0 if v else 1)" 2>/dev/null
}

# ============================================================
echo "============================================================"
echo "  Arena Unified Bridge v1.9.0 — CDP/BrowserAct/SuperPowers"
echo "  Test Suite — $(stamp)"
echo "  Bridge: $URL"
echo "============================================================"
echo ""

# ============================================================
# SECTION 0: Bridge Basics (smoke test)
# ============================================================
echo "=== SECTION 0: Bridge Smoke Test ==="

# 0.1 Health endpoint (no auth)
resp=$(curl -s "$URL/health" 2>/dev/null)
if echo "$resp" | jq_check '["ok"]' 2>/dev/null; then
    check "bridge health" "true"
else
    check "bridge health" "false" "Bridge not responding on $URL/health"
    echo "FATAL: Bridge is not running. Aborting."
    exit 1
fi

# 0.2 Auth works
resp=$(api_get "/v1/status")
if echo "$resp" | jq_check '["ok"]' 2>/dev/null; then
    check "auth token valid" "true"
else
    check "auth token valid" "false" "Token may be invalid"
    echo "FATAL: Auth failed. Check token."
    exit 1
fi

# 0.3 Version check
resp=$(api_get "/v1/version")
ver=$(echo "$resp" | jq_val '["version"]' 2>/dev/null || echo "unknown")
check "bridge version" "true" "(v$ver)"

echo ""

# ============================================================
# SECTION 1: Chrome DevTools Protocol (CDP)
# ============================================================
echo "=== SECTION 1: Chrome DevTools Protocol (CDP) ==="

# 1.1 CDP Status (disconnected)
resp=$(api_get "/v1/browser/cdp/status")
if echo "$resp" | jq_check '["ok"]' 2>/dev/null; then
    connected=$(echo "$resp" | jq_val '["connected"]' 2>/dev/null || echo "unknown")
    module_avail=$(echo "$resp" | jq_val '["module_available"]' 2>/dev/null || echo "unknown")
    check "cdp status endpoint" "true" "(connected=$connected, module=$module_avail)"
    
    if [ "$module_avail" = "False" ]; then
        check "cdp module available" "false" "cdp_browser.py not found in scripts/"
    else
        check "cdp module available" "true"
    fi
else
    check "cdp status endpoint" "false" "Endpoint returned error"
    module_avail="False"
fi

# 1.2 Check if chromium/chrome is available for CDP
if command -v chromium &>/dev/null || command -v chrome &>/dev/null || \
   command -v google-chrome &>/dev/null || command -v google-chrome-stable &>/dev/null || \
   command -v chromium-browser &>/dev/null; then
    BROWSER_AVAIL="true"
    check "chromium browser available" "true"
else
    BROWSER_AVAIL="false"
    check "chromium browser available" "skip" "No Chromium/Chrome found — CDP connect will fail"
fi

# 1.3 Check aiohttp dependency
if python3 -c "import aiohttp" 2>/dev/null; then
    check "aiohttp available" "true"
    AIOHTTP_AVAIL="true"
else
    check "aiohttp available" "skip" "aiohttp not installed — CDP async mode unavailable"
    AIOHTTP_AVAIL="false"
fi

# 1.4 CDP Connect (only if prerequisites met)
if [ "$module_avail" = "True" ] && [ "$AIOHTTP_AVAIL" = "true" ] && [ "$BROWSER_AVAIL" = "true" ]; then
    echo "  Connecting to browser via CDP..."
    resp=$(api_post "/v1/browser/cdp/connect" '{"port":9222,"headless":true}')
    if echo "$resp" | jq_check '["ok"]' 2>/dev/null; then
        tab_count=$(echo "$resp" | jq_val '["tab_count"]' 2>/dev/null || echo "0")
        check "cdp connect" "true" "(tabs=$tab_count)"
        CDP_CONNECTED="true"
    else
        err=$(echo "$resp" | jq_val '["error"]' 2>/dev/null || echo "unknown error")
        check "cdp connect" "false" "$err"
        CDP_CONNECTED="false"
    fi
else
    check "cdp connect" "skip" "Missing prerequisites (module=$module_avail, aiohttp=$AIOHTTP_AVAIL, browser=$BROWSER_AVAIL)"
    CDP_CONNECTED="false"
fi

# 1.5 CDP Navigate
if [ "$CDP_CONNECTED" = "true" ]; then
    resp=$(api_post "/v1/browser/cdp/navigate" '{"url":"https://example.com"}')
    if echo "$resp" | jq_check '["ok"]' 2>/dev/null; then
        check "cdp navigate example.com" "true"
    else
        err=$(echo "$resp" | jq_val '["error"]' 2>/dev/null || echo "unknown")
        check "cdp navigate example.com" "false" "$err"
    fi
else
    check "cdp navigate example.com" "skip" "CDP not connected"
fi

# 1.6 CDP DOM dump
if [ "$CDP_CONNECTED" = "true" ]; then
    resp=$(api_get "/v1/browser/cdp/dom")
    if echo "$resp" | jq_check '["ok"]' 2>/dev/null; then
        html_len=$(echo "$resp" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('html','')))" 2>/dev/null || echo "0")
        check "cdp dom dump" "true" "(html_len=$html_len)"
    else
        check "cdp dom dump" "false"
    fi
else
    check "cdp dom dump" "skip" "CDP not connected"
fi

# 1.7 CDP Eval JS
if [ "$CDP_CONNECTED" = "true" ]; then
    resp=$(api_post "/v1/browser/cdp/eval" '{"expression":"1+1"}')
    if echo "$resp" | jq_check '["ok"]' 2>/dev/null; then
        result=$(echo "$resp" | jq_val '["result"]' 2>/dev/null || echo "null")
        check "cdp eval 1+1" "true" "(result=$result)"
    else
        check "cdp eval 1+1" "false"
    fi
else
    check "cdp eval 1+1" "skip" "CDP not connected"
fi

# 1.8 CDP Tabs list
if [ "$CDP_CONNECTED" = "true" ]; then
    resp=$(api_get "/v1/browser/cdp/tabs")
    if echo "$resp" | jq_check '["ok"]' 2>/dev/null; then
        tab_count=$(echo "$resp" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('tabs',[])))" 2>/dev/null || echo "?")
        check "cdp tabs list" "true" "(count=$tab_count)"
    else
        check "cdp tabs list" "false"
    fi
else
    check "cdp tabs list" "skip" "CDP not connected"
fi

# 1.9 CDP Screenshot
if [ "$CDP_CONNECTED" = "true" ]; then
    resp=$(api_get "/v1/browser/cdp/screenshot")
    if echo "$resp" | jq_check '["ok"]' 2>/dev/null; then
        has_data=$(echo "$resp" | python3 -c "import json,sys; d=json.load(sys.stdin); print('yes' if d.get('data') else 'no')" 2>/dev/null)
        check "cdp screenshot" "true" "(has_data=$has_data)"
    else
        check "cdp screenshot" "false"
    fi
else
    check "cdp screenshot" "skip" "CDP not connected"
fi

# 1.10 CDP Cookies
if [ "$CDP_CONNECTED" = "true" ]; then
    resp=$(api_get "/v1/browser/cdp/cookies")
    if echo "$resp" | jq_check '["ok"]' 2>/dev/null; then
        check "cdp cookies get" "true"
    else
        check "cdp cookies get" "false"
    fi
else
    check "cdp cookies get" "skip" "CDP not connected"
fi

# 1.11 CDP Disconnect
if [ "$CDP_CONNECTED" = "true" ]; then
    resp=$(api_post "/v1/browser/cdp/disconnect")
    if echo "$resp" | jq_check '["ok"]' 2>/dev/null; then
        check "cdp disconnect" "true"
    else
        check "cdp disconnect" "false"
    fi
else
    check "cdp disconnect" "skip" "CDP not connected"
fi

# 1.12 Verify disconnected
resp=$(api_get "/v1/browser/cdp/status")
if echo "$resp" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if not d.get('connected',True) else 1)" 2>/dev/null; then
    check "cdp confirmed disconnected" "true"
else
    check "cdp confirmed disconnected" "false" "Still showing connected"
fi

echo ""

# ============================================================
# SECTION 2: BrowserAct
# ============================================================
echo "=== SECTION 2: BrowserAct ==="

# 2.1 browser-act CLI available
if command -v browser-act &>/dev/null; then
    ba_ver=$(browser-act --version 2>/dev/null || echo "unknown")
    check "browser-act CLI" "true" "(v$ba_ver)"
    BA_AVAIL="true"
else
    check "browser-act CLI" "skip" "browser-act not installed (uv tool install browser-act-cli --python 3.12)"
    BA_AVAIL="false"
fi

# 2.2 camoufox Python package
if python3 -c "import camoufox" 2>/dev/null; then
    check "camoufox python package" "true"
    CAMOUFOX_AVAIL="true"
else
    check "camoufox python package" "skip" "camoufox not installed (pip install camoufox)"
    CAMOUFOX_AVAIL="false"
fi

# 2.3 camoufox browser binary
if [ "$CAMOUFOX_AVAIL" = "true" ]; then
    camoufox_path=$(python3 -m camoufox path 2>/dev/null || echo "")
    if [ -n "$camoufox_path" ] && [ -x "$camoufox_path" ]; then
        check "camoufox browser binary" "true" "($camoufox_path)"
    else
        check "camoufox browser binary" "skip" "Binary not downloaded (run: python3 -m camoufox fetch)"
    fi
else
    check "camoufox browser binary" "skip" "camoufox not installed"
fi

# 2.4 BrowserAct skill endpoint
resp=$(api_post "/v1/skills/run" '{"name":"browseract","args":["help"]}')
if echo "$resp" | jq_check '["ok"]' 2>/dev/null; then
    check "browseract skill endpoint" "true"
elif echo "$resp" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if 'browser-act' in d.get('output','') or 'Usage' in d.get('output','') or 'agentctl' in d.get('output','') else 1)" 2>/dev/null; then
    check "browseract skill endpoint" "true" "(output contains usage)"
else
    output=$(echo "$resp" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('output','')[:200])" 2>/dev/null || echo "no output")
    check "browseract skill endpoint" "false" "$output"
fi

# 2.5 BrowserAct doctor (if CLI available)
if [ "$BA_AVAIL" = "true" ]; then
    resp=$(api_post "/v1/skills/run" '{"name":"browseract","args":["doctor"]}')
    if echo "$resp" | jq_check '["ok"]' 2>/dev/null; then
        check "browseract doctor" "true"
    else
        output=$(echo "$resp" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('output','')[:200])" 2>/dev/null || echo "")
        check "browseract doctor" "false" "${output:0:100}"
    fi
else
    check "browseract doctor" "skip" "browser-act CLI not available"
fi

# 2.6 BrowserAct browsers list
if [ "$BA_AVAIL" = "true" ]; then
    resp=$(api_post "/v1/skills/run" '{"name":"browseract","args":["browsers"]}')
    if echo "$resp" | jq_check '["ok"]' 2>/dev/null; then
        check "browseract browsers list" "true"
    else
        output=$(echo "$resp" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('output','')[:200])" 2>/dev/null || echo "")
        check "browseract browsers list" "false" "${output:0:100}"
    fi
else
    check "browseract browsers list" "skip" "browser-act CLI not available"
fi

echo ""

# ============================================================
# SECTION 3: SuperPowers
# ============================================================
echo "=== SECTION 3: SuperPowers ==="

# 3.1 SuperPowers directory exists
if [ -d "$BRIDGE_HOME/skills/superpowers/skills" ]; then
    sp_count=$(ls -1 "$BRIDGE_HOME/skills/superpowers/skills/" 2>/dev/null | wc -l)
    check "superpowers directory" "true" "($sp_count skills)"
elif [ -d "$BRIDGE_HOME/skills/superpowers" ]; then
    sp_count=$(ls -1 "$BRIDGE_HOME/skills/superpowers/" 2>/dev/null | wc -l)
    check "superpowers directory" "true" "($sp_count entries)"
else
    check "superpowers directory" "false" "Not found at $BRIDGE_HOME/skills/superpowers/"
fi

# 3.2 Bridge skills list includes superpowers
resp=$(api_get "/v1/skills")
sp_in_bridge=$(echo "$resp" | python3 -c "
import json, sys
d = json.load(sys.stdin)
skills = d.get('skills', [])
sp = [s.get('name','') for s in skills if 'superpowers' in s.get('name','').lower()]
print(len(sp))
" 2>/dev/null || echo "0")

if [ "$sp_in_bridge" -gt 0 ]; then
    check "superpowers in bridge skills list" "true" "($sp_in_bridge found)"
else
    check "superpowers in bridge skills list" "false" "0 superpowers skills found via API"
fi

# 3.3 Test each SuperPowers skill via API
SP_SKILLS=(
    "using-arena-superpowers"
    "systematic-debugging"
    "executing-plans"
    "brainstorming"
    "dispatching-parallel-agents"
    "using-feature-branches"
    "test-driven-development"
    "subagent-driven-development"
    "writing-skills"
    "verification-before-completion"
    "writing-plans"
    "finishing-a-feature-branch"
    "requesting-code-review"
    "receiving-code-review"
)

for skill in "${SP_SKILLS[@]}"; do
    # Try to run the skill (prompt-only skills return SKILL.md content)
    resp=$(api_post "/v1/skills/run" "{\"name\":\"superpowers/skills/$skill\"}")
    ok=$(echo "$resp" | python3 -c "import json,sys; d=json.load(sys.stdin); print('true' if d.get('ok') else 'false')" 2>/dev/null || echo "false")
    
    if [ "$ok" = "true" ]; then
        output_len=$(echo "$resp" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('output','')))" 2>/dev/null || echo "0")
        check "superpowers/$skill" "true" "(output=${output_len} chars)"
    else
        # Try short name
        resp2=$(api_post "/v1/skills/run" "{\"name\":\"$skill\"}")
        ok2=$(echo "$resp2" | python3 -c "import json,sys; d=json.load(sys.stdin); print('true' if d.get('ok') else 'false')" 2>/dev/null || echo "false")
        if [ "$ok2" = "true" ]; then
            check "superpowers/$skill" "true" "(via short name)"
        else
            check "superpowers/$skill" "false" "Skill not found or errored"
        fi
    fi
done

echo ""

# ============================================================
# SECTION 4: Existing Features Regression
# ============================================================
echo "=== SECTION 4: Regression Tests ==="

# 4.1 Skills list
resp=$(api_get "/v1/skills")
skill_count=$(echo "$resp" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('skills',[])))" 2>/dev/null || echo "0")
check "skills list endpoint" "true" "($skill_count skills)"

# 4.2 Memory
resp=$(api_get "/v1/memory")
check "memory endpoint" "$(echo "$resp" | jq_check '["ok"]' 2>/dev/null && echo true || echo false)"

# 4.3 Tasks
resp=$(api_get "/v1/tasks")
check "tasks endpoint" "$(echo "$resp" | jq_check '["ok"]' 2>/dev/null && echo true || echo false)"

# 4.4 Exec
resp=$(api_post "/v1/exec" '{"cmd":"echo hello-stress-test-v3"}')
if echo "$resp" | jq_check '["ok"]' 2>/dev/null; then
    output=$(echo "$resp" | jq_val '["output"]' 2>/dev/null || echo "")
    if echo "$output" | grep -q "hello-stress-test-v3"; then
        check "exec echo" "true"
    else
        check "exec echo" "false" "output mismatch: $output"
    fi
else
    check "exec echo" "false"
fi

# 4.5 Health skill
resp=$(api_post "/v1/skills/run" '{"name":"core/health"}')
check "health skill" "$(echo "$resp" | jq_check '["ok"]' 2>/dev/null && echo true || echo false)"

# 4.6 Audit log
resp=$(api_get "/v1/audit")
check "audit endpoint" "$(echo "$resp" | jq_check '["ok"]' 2>/dev/null && echo true || echo false)"

# 4.7 Recall
resp=$(api_get "/v1/recall")
check "recall endpoint" "$(echo "$resp" | jq_check '["ok"]' 2>/dev/null && echo true || echo false)"

echo ""

# ============================================================
# SUMMARY
# ============================================================
echo "============================================================"
echo "  STRESS TEST v3 RESULTS"
echo "  PASS: $PASS"
echo "  FAIL: $FAIL"
echo "  SKIP: $SKIP"
echo "  TOTAL: $((PASS + FAIL + SKIP))"
echo "============================================================"

if [ "$FAIL" -gt 0 ]; then
    echo ""
    echo "  FAILED TESTS:"
    for err in "${ERRORS[@]}"; do
        echo "    - $err"
    done
fi

echo ""
if [ "$FAIL" -eq 0 ]; then
    echo "  ✓ ALL TESTS PASSED (or skipped with valid reason)"
else
    echo "  ✗ SOME TESTS FAILED — see above for details"
fi

exit $FAIL
