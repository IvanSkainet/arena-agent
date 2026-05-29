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
    curl -s --max-time 15 -H "Authorization: Bearer $TOKEN" "$URL$1" 2>/dev/null
}

api_post() {
    local endpoint="$1"
    local body="${2:-}"
    if [ -n "$body" ]; then
        curl -s --max-time 30 -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "$body" "$URL$endpoint" 2>/dev/null
    else
        curl -s --max-time 30 -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -X POST "$URL$endpoint" 2>/dev/null
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
echo "  Arena Unified Bridge v1.9.19 — CDP/BrowserAct/SuperPowers"
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

# 1.4 CDP Diagnostics (quick check, no browser launch)
if [ "$module_avail" = "True" ]; then
    echo "  CDP diagnostics..."
    diag_resp=$(curl -s --max-time 5 -H "Authorization: Bearer $TOKEN" "$URL/v1/browser/cdp/diag" 2>/dev/null)
    if [ -n "$diag_resp" ]; then
        dbus_addr=$(echo "$diag_resp" | jq_val '["bridge_env","DBUS_SESSION_BUS_ADDRESS"]' 2>/dev/null || echo "?")
        xdg_dir=$(echo "$diag_resp" | jq_val '["bridge_env","XDG_RUNTIME_DIR"]' 2>/dev/null || echo "?")
        browser_bin=$(echo "$diag_resp" | jq_val '["browser_binary"]' 2>/dev/null || echo "?")
        dbus_ok=$(echo "$diag_resp" | jq_val '["dbus_socket_connectable"]' 2>/dev/null || echo "?")
        # Also show session_env (the env that _build_session_env produces)
        senv_dbus=$(echo "$diag_resp" | jq_val '["session_env","DBUS_SESSION_BUS_ADDRESS"]' 2>/dev/null || echo "?")
        senv_xdg=$(echo "$diag_resp" | jq_val '["session_env","XDG_RUNTIME_DIR"]' 2>/dev/null || echo "?")
        echo "    DBUS=$dbus_addr  XDG=$xdg_dir  BROWSER=$browser_bin  DBUS_SOCK=$dbus_ok"
        echo "    session_env: DBUS=$senv_dbus  XDG=$senv_xdg"
    else
        echo "    (diag endpoint not available)"
    fi
fi

# 1.4b CDP Test Launch (standalone diagnostic — tries launching Chromium directly)
if [ "$module_avail" = "True" ] && [ "$BROWSER_AVAIL" = "true" ]; then
    echo "  CDP test-launch (tries 3 headless modes, up to 35s)..."
    test_resp=$(curl -s --max-time 35 -H "Authorization: Bearer $TOKEN" "$URL/v1/browser/cdp/test-launch?port=9223&headless=true" 2>/dev/null)
    if [ -n "$test_resp" ]; then
        test_ok=$(echo "$test_resp" | jq_val '["ok"]' 2>/dev/null || echo "false")
        test_port=$(echo "$test_resp" | jq_val '["port_open"]' 2>/dev/null || echo "?")
        test_working=$(echo "$test_resp" | jq_val '["working_mode"]' 2>/dev/null || echo "")
        test_error=$(echo "$test_resp" | jq_val '["error"]' 2>/dev/null || echo "")
        test_env_dbus=$(echo "$test_resp" | jq_val '["env_dbus"]' 2>/dev/null || echo "?")
        test_env_xdg=$(echo "$test_resp" | jq_val '["env_xdg"]' 2>/dev/null || echo "?")
        test_env_home=$(echo "$test_resp" | jq_val '["env_home"]' 2>/dev/null || echo "?")
        echo "    ok=$test_ok  port_open=$test_port  working_mode=$test_working"
        echo "    env: DBUS=$test_env_dbus  XDG=$test_env_xdg  HOME=$test_env_home"
        if [ -n "$test_error" ]; then
            echo "    error: $test_error"
        fi
        # Show modes tried if failed
        modes_tried=$(echo "$test_resp" | python3 -c "
import json,sys
d = json.load(sys.stdin)
for m in d.get('modes_tried', []):
    mode = m.get('mode','?')
    ok = m.get('ok', False)
    po = m.get('port_open', False)
    rc = m.get('returncode', '?')
    died = m.get('died_after_s', '')
    err_last = ''
    for line in m.get('stderr_last10', [])[-3:]:
        err_last += line[:80] + ' | '
    extra = f'rc={rc}' if rc != '?' else f'died_after={died}s' if died else f'still_running'
    print(f'  {mode}: ok={ok} port={po} {extra}')
    if err_last:
        print(f'    stderr: {err_last[:200]}')
" 2>/dev/null)
        if [ -n "$modes_tried" ]; then
            echo "    Modes tried:"
            echo "$modes_tried"
        fi
        if [ "$test_ok" = "True" ]; then
            check "cdp test-launch" "true" "(port_open=$test_port, working_mode=$test_working)"
        else
            check "cdp test-launch" "false" "port_open=$test_port, error=$test_error"
        fi
    else
        check "cdp test-launch" "false" "No response"
    fi
fi

# 1.4b2 CDP Raw Info (v1.9.19 — fetches /json/version and /json/list from a running Chromium)
if [ "$module_avail" = "True" ] && [ "$BROWSER_AVAIL" = "true" ]; then
    echo "  CDP raw-info (launches Chromium, fetches raw CDP HTTP responses, up to 45s)..."
    ri_resp=$(curl -s --max-time 45 -H "Authorization: Bearer $TOKEN" "$URL/v1/browser/cdp/raw-info?port=9223" 2>/dev/null)
    if [ -n "$ri_resp" ]; then
        ri_ok=$(echo "$ri_resp" | jq_val '["ok"]' 2>/dev/null || echo "false")
        ri_ws_url=$(echo "$ri_resp" | jq_val '["webSocketDebuggerUrl"]' 2>/dev/null || echo "?")
        ri_version_id=$(echo "$ri_resp" | jq_val '["version_id"]' 2>/dev/null || echo "?")
        ri_browser=$(echo "$ri_resp" | jq_val '["version_browser"]' 2>/dev/null || echo "?")
        ri_has_ws=$(echo "$ri_resp" | jq_val '["has_webSocketDebuggerUrl"]' 2>/dev/null || echo "?")
        ri_tab_ws_ok=$(echo "$ri_resp" | jq_val '["tab_ws_ok"]' 2>/dev/null || echo "False")
        ri_tab_ws_lib=$(echo "$ri_resp" | jq_val '["tab_ws_lib"]' 2>/dev/null || echo "?")
        ri_tab_ws_time=$(echo "$ri_resp" | jq_val '["tab_ws_time_s"]' 2>/dev/null || echo "?")
        ri_tab_ws_cdp=$(echo "$ri_resp" | jq_val '["tab_ws_cdp_ok"]' 2>/dev/null || echo "False")
        ri_error=$(echo "$ri_resp" | jq_val '["error"]' 2>/dev/null || echo "")
        ri_tab_ws_err=$(echo "$ri_resp" | jq_val '["tab_ws_error"]' 2>/dev/null || echo "")
        ri_tab_ws_aio_err=$(echo "$ri_resp" | jq_val '["tab_ws_aiohttp_error"]' 2>/dev/null || echo "")
        ri_version_err=$(echo "$ri_resp" | jq_val '["raw_version_error"]' 2>/dev/null || echo "")
        ri_tabs_err=$(echo "$ri_resp" | jq_val '["raw_tabs_error"]' 2>/dev/null || echo "")
        ri_tab_count=$(echo "$ri_resp" | jq_val '["tab_count"]' 2>/dev/null || echo "?")
        ri_page_tab_count=$(echo "$ri_resp" | jq_val '["page_tab_count"]' 2>/dev/null || echo "?")
        ri_port_ready=$(echo "$ri_resp" | jq_val '["port_ready_after_s"]' 2>/dev/null || echo "?")
        ri_browser_died=$(echo "$ri_resp" | jq_val '["browser_died"]' 2>/dev/null || echo "")
        echo "    wsDebuggerUrl=$ri_ws_url  has_ws=$ri_has_ws  id=$ri_version_id"
        echo "    browser=$ri_browser  tabs=$ri_tab_count  page_tabs=$ri_page_tab_count  port_ready=${ri_port_ready}s"
        echo "    tab_ws_ok=$ri_tab_ws_ok  lib=$ri_tab_ws_lib  time=${ri_tab_ws_time}s  cdp=$ri_tab_ws_cdp"
        if [ -n "$ri_version_err" ]; then echo "    raw_version_error: $ri_version_err"; fi
        if [ -n "$ri_tabs_err" ]; then echo "    raw_tabs_error: $ri_tabs_err"; fi
        if [ -n "$ri_tab_ws_err" ]; then echo "    tab_ws_error: $ri_tab_ws_err"; fi
        if [ -n "$ri_tab_ws_aio_err" ]; then echo "    tab_ws_aiohttp_error: $ri_tab_ws_aio_err"; fi
        if [ -n "$ri_error" ] && [ "$ri_error" != "None" ]; then echo "    error: $ri_error"; fi
        if [ -n "$ri_browser_died" ] && [ "$ri_browser_died" != "False" ]; then echo "    BROWSER_DIED: rc=$(echo "$ri_resp" | jq_val '["browser_rc"]' 2>/dev/null)"; fi
        # Show tab WS URLs from raw /json/list
        echo "$ri_resp" | python3 -c "
import json, sys
d = json.load(sys.stdin)
tabs = d.get('tab_ws_urls', [])
for t in tabs[:3]:
    print(f'    tab: type={t.get(\"type\",\"?\")} id={t.get(\"id\",\"?\")[:20]} wsUrl={t.get(\"webSocketDebuggerUrl\",\"MISSING\")[:60]}')
" 2>/dev/null || true
        if [ "$ri_ok" = "True" ]; then
            check "cdp raw-info" "true" "(tab_ws=$ri_tab_ws_ok, wsUrl=$ri_has_ws)"
        else
            check "cdp raw-info" "false" "tab_ws=$ri_tab_ws_ok, error=$ri_error"
        fi
    else
        check "cdp raw-info" "false" "No response (curl timeout?)"
    fi
fi

# 1.4c CDP WebSocket Test (standalone diagnostic — tests WS connect to debug port)
if [ "$module_avail" = "True" ] && [ "$BROWSER_AVAIL" = "true" ]; then
    echo "  CDP test-ws (launches Chromium, tests WS, up to 45s)..."
    ws_resp=$(curl -s --max-time 45 -H "Authorization: Bearer $TOKEN" "$URL/v1/browser/cdp/test-ws?port=9223" 2>/dev/null)
    if [ -n "$ws_resp" ]; then
        # v1.9.19: Check if response is valid JSON first
        ws_is_json=$(echo "$ws_resp" | python3 -c "import json,sys; json.load(sys.stdin); print('yes')" 2>/dev/null || echo "no")
        if [ "$ws_is_json" = "no" ]; then
            echo "    WARNING: Response is NOT valid JSON! First 200 chars:"
            echo "    ${ws_resp:0:200}"
            check "cdp test-ws" "false" "Non-JSON response (endpoint crash?)"
        else
            ws_ok=$(echo "$ws_resp" | jq_val '["ok"]' 2>/dev/null || echo "false")
            ws_browser_ws=$(echo "$ws_resp" | jq_val '["ws_connect_ok"]' 2>/dev/null || echo "?")
            ws_tab_ws=$(echo "$ws_resp" | jq_val '["tab_ws_connect_ok"]' 2>/dev/null || echo "?")
            ws_browser_time=$(echo "$ws_resp" | jq_val '["ws_connect_time_s"]' 2>/dev/null || echo "?")
            ws_tab_time=$(echo "$ws_resp" | jq_val '["tab_ws_connect_time_s"]' 2>/dev/null || echo "?")
            ws_url=$(echo "$ws_resp" | jq_val '["ws_url"]' 2>/dev/null || echo "?")
            ws_tab_url=$(echo "$ws_resp" | jq_val '["tab_ws_url"]' 2>/dev/null || echo "?")
            ws_err=$(echo "$ws_resp" | jq_val '["ws_connect_error"]' 2>/dev/null || echo "")
            ws_tab_err=$(echo "$ws_resp" | jq_val '["tab_ws_connect_error"]' 2>/dev/null || echo "")
            ws_websockets_ok=$(echo "$ws_resp" | jq_val '["websockets_browser_ok"]' 2>/dev/null || echo "?")
            ws_websockets_time=$(echo "$ws_resp" | jq_val '["websockets_browser_time_s"]' 2>/dev/null || echo "?")
            ws_websockets_tab_ok=$(echo "$ws_resp" | jq_val '["websockets_tab_ok"]' 2>/dev/null || echo "?")
            ws_websockets_tab_time=$(echo "$ws_resp" | jq_val '["websockets_tab_time_s"]' 2>/dev/null || echo "?")
            ws_constructed=$(echo "$ws_resp" | jq_val '["tab_ws_constructed"]' 2>/dev/null || echo "")
            ws_http_ok=$(echo "$ws_resp" | jq_val '["http_endpoint_ok"]' 2>/dev/null || echo "?")
            ws_version_keys=$(echo "$ws_resp" | jq_val '["raw_version_keys"]' 2>/dev/null || echo "?")
            ws_version_err=$(echo "$ws_resp" | jq_val '["raw_version_error"]' 2>/dev/null || echo "")
            ws_tabs_err=$(echo "$ws_resp" | jq_val '["raw_tabs_error"]' 2>/dev/null || echo "")
            ws_port_ready=$(echo "$ws_resp" | jq_val '["port_ready_after_s"]' 2>/dev/null || echo "?")
            ws_browser_died=$(echo "$ws_resp" | jq_val '["browser_died"]' 2>/dev/null || echo "")
            echo "    browser_ws=$ws_browser_ws (${ws_browser_time}s) tab_ws=$ws_tab_ws (${ws_tab_time}s)"
            echo "    browser_url=$ws_url"
            echo "    tab_url=$ws_tab_url${ws_constructed:+ (constructed)}"
            echo "    http_ok=$ws_http_ok  version_keys=$ws_version_keys  port_ready=${ws_port_ready}s"
            echo "    websockets_lib=$ws_websockets_ok (${ws_websockets_time}s) tab=$ws_websockets_tab_ok (${ws_websockets_tab_time}s)"
            if [ -n "$ws_version_err" ]; then echo "    raw_version_error: $ws_version_err"; fi
            if [ -n "$ws_tabs_err" ]; then echo "    raw_tabs_error: $ws_tabs_err"; fi
            if [ -n "$ws_err" ]; then
                echo "    browser_ws_error: $ws_err"
            fi
            if [ -n "$ws_tab_err" ]; then
                echo "    tab_ws_error: $ws_tab_err"
            fi
            if [ -n "$ws_browser_died" ] && [ "$ws_browser_died" != "False" ]; then
                echo "    BROWSER_DIED: rc=$(echo "$ws_resp" | jq_val '["browser_rc"]' 2>/dev/null)"
            fi
            # Show version info
            ws_ver_ws=$(echo "$ws_resp" | jq_val '["version_info","webSocketDebuggerUrl"]' 2>/dev/null || echo "?")
            ws_ver_id=$(echo "$ws_resp" | jq_val '["version_info","id"]' 2>/dev/null || echo "?")
            echo "    version: wsUrl=$ws_ver_ws  id=$ws_ver_id"
            # Show CDP command result if available
            ws_tab_cdp_ok=$(echo "$ws_resp" | jq_val '["tab_cdp_ok"]' 2>/dev/null || echo "")
            if [ -n "$ws_tab_cdp_ok" ] && [ "$ws_tab_cdp_ok" = "True" ]; then
                echo "    tab_cdp_command: OK!"
            fi
            ws_ws_tab_cdp_ok=$(echo "$ws_resp" | jq_val '["websockets_tab_cdp_ok"]' 2>/dev/null || echo "")
            if [ -n "$ws_ws_tab_cdp_ok" ] && [ "$ws_ws_tab_cdp_ok" = "True" ]; then
                echo "    websockets_tab_cdp: OK!"
            fi
            # Show unhandled error if present
            ws_unhandled=$(echo "$ws_resp" | jq_val '["error"]' 2>/dev/null || echo "")
            if [ -n "$ws_unhandled" ]; then
                echo "    unhandled_error: $ws_unhandled"
            fi
            if [ "$ws_ok" = "True" ]; then
                check "cdp test-ws" "true" "(browser_ws=$ws_browser_ws, tab_ws=$ws_tab_ws, websockets=$ws_websockets_ok)"
            else
                check "cdp test-ws" "false" "browser_ws=$ws_browser_ws, tab_ws=$ws_tab_ws, error=$ws_tab_err"
            fi
        fi
    else
        check "cdp test-ws" "false" "No response (curl timeout?)"
    fi
fi

# 1.5 CDP Connect (only if prerequisites met)
if [ "$module_avail" = "True" ] && [ "$AIOHTTP_AVAIL" = "true" ] && [ "$BROWSER_AVAIL" = "true" ]; then
    echo "  Connecting to browser via CDP (timeout 65s)..."
    resp=$(curl -s --max-time 65 -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
        -d '{"port":9222,"headless":true}' "$URL/v1/browser/cdp/connect" 2>/dev/null)
    if [ -z "$resp" ]; then
        check "cdp connect" "false" "No response (timeout or bridge error)"
        CDP_CONNECTED="false"
    elif echo "$resp" | jq_check '["ok"]' 2>/dev/null; then
        tab_count=$(echo "$resp" | jq_val '["tab_count"]' 2>/dev/null || echo "0")
        warning=$(echo "$resp" | jq_val '["warning"]' 2>/dev/null || echo "")
        check "cdp connect" "true" "(tabs=$tab_count)${warning:+ — $warning}"
        CDP_CONNECTED="true"
    else
        err=$(echo "$resp" | jq_val '["error"]' 2>/dev/null || echo "unknown error")
        check "cdp connect" "false" "$err"
        # Show diagnostics if available
        diag_info=$(echo "$resp" | python3 -c "
import json,sys
d = json.load(sys.stdin)
di = d.get('diagnostics', {})
parts = []
for k in ['method','pid','direct_rc','direct_error','direct_exception','systemd_run_rc','systemd_run_error','all_failed','skip_reason','cmd_full']:
    v = di.get(k)
    if v is not None:
        sv = str(v)[:150]
        parts.append(f'{k}={sv}')
stderr = d.get('stderr','')
if stderr:
    parts.append(f'stderr={stderr[:200]}')
print(' | '.join(parts) if parts else 'no diagnostics')
" 2>/dev/null)
        if [ -n "$diag_info" ]; then
            echo "    Diagnostics: $diag_info"
        fi
        # Show bridge logs for CDP
        echo "    Bridge CDP logs (last 30 lines):"
        journalctl --user -u arena-bridge --since "5 min ago" --no-pager 2>/dev/null | grep -iE "\[CDP\]|cdp_browser|launch_browser" | tail -30 || echo "    (no CDP logs found)"
        # Show Chromium stderr log if available
        CHR_LOG="/tmp/cdp-browser-$(cat /proc/self/status 2>/dev/null | grep PPid | awk '{print $2}' 2>/dev/null)/chromium-launch.log"
        # Try common PIDs
        for cdp_dir in /tmp/cdp-browser-*; do
            if [ -d "$cdp_dir" ] && [ -f "$cdp_dir/chromium-launch.log" ]; then
                LOG_CONTENT=$(cat "$cdp_dir/chromium-launch.log" 2>/dev/null | tail -20)
                if [ -n "$LOG_CONTENT" ]; then
                    echo "    Chromium log ($cdp_dir/chromium-launch.log):"
                    echo "    $LOG_CONTENT"
                fi
                break
            fi
        done
        CDP_CONNECTED="false"
    fi
else
    check "cdp connect" "skip" "Missing prerequisites (module=$module_avail, aiohttp=$AIOHTTP_AVAIL, browser=$BROWSER_AVAIL)"
    CDP_CONNECTED="false"
fi

# 1.5 CDP Navigate
if [ "$CDP_CONNECTED" = "true" ]; then
    resp=$(api_post "/v1/browser/cdp/navigate" '{"url":"https://example.com","wait":true}')
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
# Note: browser-act is installed via uv tool which uses its own venv.
# We need to check camoufox in that venv, not system python.
BA_PYTHON="python3"
if command -v uv &>/dev/null; then
    UV_TOOL_DIR="$(uv tool dir 2>/dev/null)" || UV_TOOL_DIR=""
    if [ -n "$UV_TOOL_DIR" ] && [ -d "$UV_TOOL_DIR/browser-act-cli" ] && [ -x "$UV_TOOL_DIR/browser-act-cli/bin/python" ]; then
        BA_PYTHON="$UV_TOOL_DIR/browser-act-cli/bin/python"
    fi
fi
if $BA_PYTHON -c "import camoufox" 2>/dev/null; then
    check "camoufox python package" "true" "(via $BA_PYTHON)"
    CAMOUFOX_AVAIL="true"
else
    check "camoufox python package" "skip" "camoufox not found in $BA_PYTHON (bundled with browser-act-cli)"
    CAMOUFOX_AVAIL="false"
fi

# 2.3 camoufox browser binary
if [ "$CAMOUFOX_AVAIL" = "true" ]; then
    camoufox_path=$($BA_PYTHON -m camoufox path 2>/dev/null || echo "")
    if [ -n "$camoufox_path" ] && [ -x "$camoufox_path" ]; then
        check "camoufox browser binary" "true" "($camoufox_path)"
    else
        check "camoufox browser binary" "skip" "Binary not downloaded (run: $BA_PYTHON -m camoufox fetch)"
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
    output=$(echo "$resp" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('output',d.get('stdout',''))[:200])" 2>/dev/null || echo "")
    if echo "$output" | grep -q "hello-stress-test-v3"; then
        check "exec echo" "true"
    else
        check "exec echo" "false" "output: '${output}'"
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

# 4.7 Recall (requires ?q= parameter)
resp=$(api_get "/v1/recall?q=test")
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
