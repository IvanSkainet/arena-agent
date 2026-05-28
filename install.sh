#!/usr/bin/env bash
# ============================================================
#  Arena Unified Bridge — Universal Installer (Linux/macOS)
#  Downloads the latest version from GitHub, sets up everything
#  in one directory. No scattered files across home.
#  Run:  curl -fsSL https://raw.githubusercontent.com/IvanSkainet/arena-agent/master/install.sh | bash
# ============================================================
set -euo pipefail

REPO="IvanSkainet/arena-agent"
BRANCH="master"
INSTALL_DIR="${ARENA_INSTALL_DIR:-$HOME/arena-bridge}"
PORT="${ARENA_PORT:-8765}"
PROFILE="owner-shell"

ok()   { echo -e "\033[32m[OK]\033[0m $*"; }
warn() { echo -e "\033[33m[WARN]\033[0m $*"; }
err()  { echo -e "\033[31m[ERROR]\033[0m $*"; }
info() { echo -e "\033[34m[INFO]\033[0m $*"; }
ask()  { echo -en "\033[36m[?] $* [y/N]: \033[0m"; read -r REPLY; [[ "$REPLY" =~ ^[Yy]$ ]]; }

echo ""
echo "========================================"
echo " Arena Unified Bridge — Installer"
echo "========================================"
echo ""

# --- Step 1: Download or update the repo ---
if [ -d "$INSTALL_DIR/.git" ]; then
    info "Updating existing installation at $INSTALL_DIR ..."
    cd "$INSTALL_DIR"
    # First try: normal pull
    if ! git pull --ff-only 2>/dev/null; then
        # If pull fails due to untracked files that conflict, move them aside
        CONFLICTING=$(git pull --ff-only 2>&1 | grep -oE 'skills/[^ ]+SKILL\.md' || true)
        if [ -n "$CONFLICTING" ]; then
            info "Resolving untracked file conflicts..."
            echo "$CONFLICTING" | while read -r f; do
                if [ -f "$f" ]; then
                    mv "$f" "${f}.local" 2>/dev/null || rm -f "$f" 2>/dev/null
                fi
            done
            # Retry pull
            if git pull --ff-only 2>/dev/null; then
                ok "Update successful after resolving conflicts"
            else
                warn "git pull still failed, using existing code"
            fi
        else
            warn "git pull failed, using existing code"
        fi
    fi
else
    info "Downloading Arena Unified Bridge from GitHub ..."
    git clone --depth 1 -b "$BRANCH" "https://github.com/$REPO.git" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# --- Read version from the bridge itself ---
BRIDGE_PY="$INSTALL_DIR/unified_bridge.py"
if [ ! -f "$BRIDGE_PY" ]; then
    err "unified_bridge.py not found in $INSTALL_DIR"
    exit 1
fi
VERSION="$(grep -m1 '^VERSION = ' "$BRIDGE_PY" | cut -d'"' -f2)"
if [ -z "$VERSION" ]; then
    VERSION="unknown"
fi
ok "Bridge v$VERSION downloaded"

# --- Step 2: Check Python ---
PY=""
for cand in python3.14 python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then PY="$(command -v "$cand")"; break; fi
done
if [ -z "$PY" ]; then
    err "Python 3.10+ not found. Install it first."
    exit 1
fi
PYVER=$("$PY" --version 2>&1 | cut -d' ' -f2)
ok "Python $PYVER found"

# --- Step 3: Install dependencies ---
info "Installing Python dependencies..."
"$PY" -m pip install aiohttp psutil --quiet 2>/dev/null || true
ok "Python packages ready"

# --- Step 4: Create subdirectories (all inside INSTALL_DIR) ---
info "Creating directory structure..."
for d in "$INSTALL_DIR/memory" "$INSTALL_DIR/missions" \
         "$INSTALL_DIR/queue/inbox" "$INSTALL_DIR/queue/running" "$INSTALL_DIR/queue/done" "$INSTALL_DIR/queue/failed" \
         "$INSTALL_DIR/reports" "$INSTALL_DIR/logs" "$INSTALL_DIR/backups" \
         "$INSTALL_DIR/hooks/pre_skill.d" "$INSTALL_DIR/hooks/post_skill.d" \
         "$INSTALL_DIR/skills" "$INSTALL_DIR/subagents" "$INSTALL_DIR/mcp" \
         "$INSTALL_DIR/projects" "$INSTALL_DIR/scripts" "$INSTALL_DIR/bin"; do
    mkdir -p "$d"
done
ok "Directories ready"

# ============================================================
# Step 4b: Migration from old versions
# ============================================================
OLD_DIRS=("$HOME/.arena-local-bridge" "$HOME/.arena-agent" "$HOME/arena-agent")
FOUND_OLD=false

for OLD_DIR in "${OLD_DIRS[@]}"; do
    if [ -d "$OLD_DIR" ]; then
        if [ "$FOUND_OLD" = false ]; then
            echo ""
            echo "========================================"
            echo " Migration from Old Versions"
            echo "========================================"
            echo ""
            FOUND_OLD=true
        fi
        info "Found old installation directory: $OLD_DIR"

        # --- Migrate token.txt ---
        if [ -f "$OLD_DIR/token.txt" ] && [ ! -f "$INSTALL_DIR/token.txt" ]; then
            if ask "Copy token.txt from $OLD_DIR to $INSTALL_DIR?"; then
                cp "$OLD_DIR/token.txt" "$INSTALL_DIR/token.txt" || true
                chmod 600 "$INSTALL_DIR/token.txt" || true
                ok "token.txt migrated"
            fi
        fi

        # --- Migrate audit.jsonl ---
        if [ -f "$OLD_DIR/audit.jsonl" ] && [ ! -f "$INSTALL_DIR/audit.jsonl" ]; then
            if ask "Copy audit.jsonl from $OLD_DIR to $INSTALL_DIR?"; then
                cp "$OLD_DIR/audit.jsonl" "$INSTALL_DIR/audit.jsonl" || true
                ok "audit.jsonl migrated"
            fi
        fi

        # --- Migrate current_project ---
        if [ -f "$OLD_DIR/current_project" ] && [ ! -f "$INSTALL_DIR/current_project" ]; then
            if ask "Copy current_project from $OLD_DIR to $INSTALL_DIR?"; then
                cp "$OLD_DIR/current_project" "$INSTALL_DIR/current_project" || true
                ok "current_project migrated"
            fi
        fi

        # --- Warn about queue items ---
        if [ -d "$OLD_DIR/queue" ]; then
            QUEUE_COUNT="$(find "$OLD_DIR/queue" -type f 2>/dev/null | wc -l || true)"
            if [ "$QUEUE_COUNT" -gt 0 ] 2>/dev/null; then
                warn "Old directory has $QUEUE_COUNT item(s) in queue/ — these will NOT be migrated automatically"
            fi
        fi

        # --- Offer to remove old directory ---
        read -rp "$(echo -e '\033[36m[?] Remove old directory '"$OLD_DIR"'? [y/N]: \033[0m')" REMOVE_REPLY || true
        if [[ "$REMOVE_REPLY" =~ ^[Yy]$ ]]; then
            rm -rf "$OLD_DIR" || true
            ok "Removed $OLD_DIR"
        else
            info "Kept $OLD_DIR — you can remove it manually later"
        fi

        echo ""
    fi
done

if [ "$FOUND_OLD" = true ]; then
    ok "Migration check complete"
fi

# --- Step 5: Generate or preserve token ---
TOKEN_FILE="$INSTALL_DIR/token.txt"
TOKEN=""
if [ -f "$TOKEN_FILE" ]; then
    TOKEN="$(head -1 "$TOKEN_FILE" | tr -d '[:space:]')"
    if [ ${#TOKEN} -lt 16 ]; then
        TOKEN=""
    fi
fi
if [ -z "$TOKEN" ]; then
    TOKEN="$("$PY" -c "import secrets; print(secrets.token_urlsafe(32))")"
    echo "$TOKEN" > "$TOKEN_FILE"
    chmod 600 "$TOKEN_FILE"
    ok "New token generated"
else
    ok "Existing token preserved"
fi

# ============================================================
# Step 6: Optional components
# ============================================================
echo ""
echo "========================================"
echo " Optional Components"
echo "========================================"
echo ""

# --- 6a: Tailscale ---
if command -v tailscale >/dev/null 2>&1; then
    # Check if Tailscale is logged in by checking DNSName from JSON output
    TS_DNSNAME="$(tailscale status --json 2>/dev/null | "$PY" -c "
import json, sys
try:
    d = json.load(sys.stdin)
    dns = d.get('Self', {}).get('DNSName', '') or d.get('DNSName', '')
    if dns: print(dns.rstrip('.'))
except: pass
" 2>/dev/null)" || TS_DNSNAME=""
    if [ -n "$TS_DNSNAME" ]; then
        ok "Tailscale connected: $TS_DNSNAME"
    else
        warn "Tailscale is installed but not logged in"
        if [ "$(uname -s)" = "Linux" ]; then
            if ask "Run Tailscale login? (requires sudo)"; then
                sudo tailscale login 2>&1 && ok "Tailscale login initiated — follow the URL in output" || warn "Tailscale login failed"
            else
                info "You can login later: sudo tailscale login"
            fi
        else
            if ask "Run Tailscale login?"; then
                tailscale login 2>&1 && ok "Tailscale login initiated — follow the URL in output" || warn "Tailscale login failed"
            else
                info "You can login later: tailscale login"
            fi
        fi
    fi
else
    info "Tailscale not found. Install it for internet access: https://tailscale.com"
fi

# --- 6b: SuperPowers (agentic skills framework) ---
SP_DIR="$INSTALL_DIR/skills/superpowers/skills"
if [ -d "$SP_DIR" ]; then
    SP_COUNT=$(ls -1 "$SP_DIR" 2>/dev/null | wc -l)
    ok "SuperPowers already installed — $SP_COUNT skills in skills/superpowers/skills/"
else
    # Check if bundled in repo (skills/superpowers/skills/ ships with the repo)
    BUNDLED_SP="$INSTALL_DIR/skills/superpowers/skills"
    if [ -d "$BUNDLED_SP" ]; then
        SP_COUNT=$(ls -1 "$BUNDLED_SP" 2>/dev/null | wc -l)
        ok "SuperPowers bundled — $SP_COUNT skills available"
    else
        if ask "Install SuperPowers? (agentic TDD, debugging, planning skills for AI agents)"; then
            info "Cloning SuperPowers from GitHub..."
            git clone --depth 1 https://github.com/obra/superpowers.git "$INSTALL_DIR/skills/superpowers" 2>/dev/null
            if [ -d "$INSTALL_DIR/skills/superpowers/skills" ]; then
                ok "SuperPowers installed — 14 skills available (TDD, debugging, planning, etc.)"
            else
                warn "SuperPowers clone failed. You can install later:"
                echo "  git clone https://github.com/obra/superpowers.git $INSTALL_DIR/skills/superpowers"
            fi
        else
            info "SuperPowers skipped. Install later with:"
            echo "  git clone https://github.com/obra/superpowers.git $INSTALL_DIR/skills/superpowers"
        fi
    fi
fi

# --- 6c: BrowserAct (browser automation for AI agents) ---
if command -v browser-act >/dev/null 2>&1; then
    ok "BrowserAct already installed: $(browser-act --version 2>/dev/null || echo 'installed')"
else
    # Check for uv
    if command -v uv >/dev/null 2>&1; then
        if ask "Install BrowserAct? (browser automation CLI for AI agents — browse, click, forms, CAPTCHAs)"; then
            info "Installing BrowserAct via uv..."
            uv tool install browser-act-cli --python 3.12 2>/dev/null
            if command -v browser-act >/dev/null 2>&1; then
                ok "BrowserAct installed: $(browser-act --version 2>/dev/null || echo 'OK')"
            else
                warn "BrowserAct installation may have failed. Install manually:"
                echo "  uv tool install browser-act-cli --python 3.12"
            fi
        else
            info "BrowserAct skipped. Install later with:"
            echo "  uv tool install browser-act-cli --python 3.12"
        fi
    else
        info "BrowserAct requires 'uv' package manager. Install uv first:"
        echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
        echo "  Then: uv tool install browser-act-cli --python 3.12"
    fi
fi

# --- 6d: Camoufox (stealth browser engine for BrowserAct) ---
# camoufox is bundled as a pip dependency of browser-act-cli, but the
# browser binary (~300MB) must be downloaded separately.
if command -v browser-act >/dev/null 2>&1; then
    # Check if camoufox Python package is available (it's a dependency of browser-act-cli)
    # We need to find the Python that browser-act uses (it's installed via uv tool)
    BA_PYTHON=""
    # uv tool installs use their own venv — find it
    if command -v uv >/dev/null 2>&1; then
        BA_VENV="$(uv tool dir 2>/dev/null)/browser-act-cli" || BA_VENV=""
        if [ -n "$BA_VENV" ] && [ -d "$BA_VENV" ]; then
            BA_PYTHON="$BA_VENV/bin/python"
        fi
    fi
    # Fallback: try the system python with camoufox
    if [ -z "$BA_PYTHON" ] || [ ! -x "$BA_PYTHON" ]; then
        BA_PYTHON="$PY"
    fi

    CAMOUFOX_CHECK="$($BA_PYTHON -c 'import camoufox; print("ok")' 2>/dev/null)" || CAMOUFOX_CHECK=""
    if [ "$CAMOUFOX_CHECK" = "ok" ]; then
        # Check if browser binary is already downloaded
        CAMOUFOX_PATH="$($BA_PYTHON -m camoufox path 2>/dev/null)" || CAMOUFOX_PATH=""
        if [ -n "$CAMOUFOX_PATH" ] && [ -x "$CAMOUFOX_PATH" ]; then
            ok "Camoufox stealth browser ready: $CAMOUFOX_PATH"
        else
            if ask "Download Camoufox stealth browser? (~300MB, enables BrowserAct stealth mode)"; then
                info "Downloading Camoufox browser binary..."
                $BA_PYTHON -m camoufox fetch 2>&1
                CAMOUFOX_PATH="$($BA_PYTHON -m camoufox path 2>/dev/null)" || CAMOUFOX_PATH=""
                if [ -n "$CAMOUFOX_PATH" ] && [ -x "$CAMOUFOX_PATH" ]; then
                    ok "Camoufox stealth browser downloaded: $CAMOUFOX_PATH"
                else
                    warn "Camoufox binary download may have failed. Try manually:"
                    echo "  $BA_PYTHON -m camoufox fetch"
                fi
            else
                info "Camoufox browser skipped. Download later with:"
                echo "  $BA_PYTHON -m camoufox fetch"
                info "BrowserAct will still work with regular Chrome/Chromium."
            fi
        fi
    else
        info "Camoufox Python package not found. BrowserAct stealth mode may not work."
        info "It should be auto-installed with browser-act-cli. Try:"
        echo "  uv tool install browser-act-cli --python 3.12 --force-reinstall"
    fi
elif [ -d "$INSTALL_DIR/skills/browseract" ]; then
    info "BrowserAct skill files present but browser-act CLI not found."
    info "Install BrowserAct first: uv tool install browser-act-cli --python 3.12"
fi

echo ""

# ============================================================
# Step 7: Install as system service
# ============================================================
info "Installing as system service..."
OS="$(uname -s)"

# Escape path for systemd (handles special chars, spaces, unicode)
systemd_escape() {
    python3 -c "import re, sys; p=sys.argv[1]; print(re.sub(r'([^a-zA-Z0-9/_.-])', lambda m: '\\x{:02x}'.format(ord(m.group(1))), p))" "$1" 2>/dev/null || echo "$1"
}

if [ "$OS" = "Linux" ] && command -v systemctl >/dev/null 2>&1; then
    SD_DIR="$HOME/.config/systemd/user"
    mkdir -p "$SD_DIR"

    ESCAPED_BRIDGE_PY=$(systemd_escape "$BRIDGE_PY")
    ESCAPED_TOKEN_FILE=$(systemd_escape "$TOKEN_FILE")
    ESCAPED_INSTALL_DIR=$(systemd_escape "$INSTALL_DIR")

    cat > "$SD_DIR/arena-bridge.service" << EOF
[Unit]
Description=Arena Unified Bridge v${VERSION}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=${PY} -u ${ESCAPED_BRIDGE_PY} serve --root ${HOME} --profile ${PROFILE} --port ${PORT}
WorkingDirectory=${ESCAPED_INSTALL_DIR}
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1
Environment=ARENA_AGENT_HOME=${ESCAPED_INSTALL_DIR}
Environment=ARENA_TOKEN_FILE=${ESCAPED_TOKEN_FILE}

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable arena-bridge.service
    systemctl --user restart arena-bridge.service
    ok "systemd service installed and started"

elif [ "$OS" = "Darwin" ]; then
    PLIST_DIR="$HOME/Library/LaunchAgents"
    mkdir -p "$PLIST_DIR"
    PLIST="$PLIST_DIR/com.arena.bridge.plist"
    cat > "$PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.arena.bridge</string>
    <key>ProgramArguments</key><array>
        <string>${PY}</string>
        <string>-u</string>
        <string>${BRIDGE_PY}</string>
        <string>serve</string>
        <string>--root</string><string>${HOME}</string>
        <string>--profile</string><string>${PROFILE}</string>
        <string>--port</string><string>${PORT}</string>
    </array>
    <key>EnvironmentVariables</key><dict>
        <key>ARENA_AGENT_HOME</key><string>${INSTALL_DIR}</string>
        <key>ARENA_TOKEN_FILE</key><string>${TOKEN_FILE}</string>
    </dict>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>${INSTALL_DIR}/logs/bridge.log</string>
    <key>StandardErrorPath</key><string>${INSTALL_DIR}/logs/bridge_err.log</string>
</dict>
</plist>
EOF
    launchctl unload "$PLIST" 2>/dev/null || true
    launchctl load "$PLIST" 2>/dev/null
    ok "launchd service installed"

else
    info "No systemd/launchd detected. Starting with nohup."
    PIDS="$(lsof -ti :"$PORT" 2>/dev/null || true)"
    [ -n "$PIDS" ] && kill $PIDS 2>/dev/null || true
    ARENA_TOKEN_FILE="$TOKEN_FILE" nohup "$PY" -u "$BRIDGE_PY" serve --root "$HOME" --profile "$PROFILE" --port "$PORT" \
        >> "$INSTALL_DIR/logs/bridge.log" 2>&1 &
    ok "Bridge started with nohup (won't survive reboot)"
fi

# --- Step 8: Wait for bridge to come up ---
info "Waiting for bridge to start..."
for i in $(seq 1 20); do
    if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
        ok "Bridge is healthy! v${VERSION}"
        break
    fi
    sleep 1
    if [ "$i" -eq 20 ]; then
        warn "Bridge not responding after 20s."
        echo "  Check: journalctl --user -u arena-bridge -n 50"
        echo "  Or:    cat $INSTALL_DIR/logs/bridge.log"
    fi
done

# --- Detect Tailscale URL ---
# Try multiple methods — this must work for ALL users on ALL platforms
TS_URL=""
# Method 1: Query the bridge API (most reliable — bridge already knows)
if [ -z "$TS_URL" ]; then
    TS_URL="$(curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:$PORT/v1/sys/funnel" 2>/dev/null | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    url = d.get('funnel', {}).get('url', '')
    if url:
        print(url)
except: pass
" 2>/dev/null)" || TS_URL=""
fi
# Method 2: tailscale status --json, read Self.DNSName
if [ -z "$TS_URL" ] && command -v tailscale >/dev/null 2>&1; then
    TS_URL="$(tailscale status --json 2>/dev/null | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    # DNSName is in Self object, not at root level
    dns = d.get('Self', {}).get('DNSName', '') or d.get('DNSName', '')
    if dns:
        dns = dns.rstrip('.')
        if not dns.startswith('https://'):
            dns = 'https://' + dns
        print(dns)
except: pass
" 2>/dev/null)" || TS_URL=""
fi
# Method 3: Parse from tailscale status text (works even without --json)
if [ -z "$TS_URL" ] && command -v tailscale >/dev/null 2>&1; then
    TS_URL="$(tailscale status 2>/dev/null | grep -oE 'https://[a-z0-9-]+\.tail[0-9]+\.ts\.net' | head -1)" || TS_URL=""
fi

# --- Done ---
echo ""
echo "========================================"
echo " INSTALLATION COMPLETE"
echo "========================================"
echo ""
echo " Directory:  $INSTALL_DIR"
echo " Dashboard:  http://127.0.0.1:$PORT/gui"
echo " Health:     http://127.0.0.1:$PORT/health"
echo " Token file: $TOKEN_FILE"
echo ""
echo " Your token:"
echo "   $TOKEN"
if [ -n "$TS_URL" ]; then
    echo ""
    echo " Your secure Tailscale URL:"
    echo "   $TS_URL"
fi
echo ""
if [ "$OS" = "Linux" ]; then
    echo " Manage:"
    echo "   systemctl --user status   arena-bridge"
    echo "   systemctl --user restart  arena-bridge"
    echo "   systemctl --user stop     arena-bridge"
    echo "   journalctl --user -u arena-bridge -f"
elif [ "$OS" = "Darwin" ]; then
    echo " Manage:"
    echo "   launchctl print gui/\$UID/com.arena.bridge"
    echo "   launchctl kickstart -k gui/\$UID/com.arena.bridge"
fi
echo ""
echo " Optional:"
echo "   tailscale funnel --bg $PORT   # expose to internet"
echo ""
echo " Installed skills:"
[ -d "$INSTALL_DIR/skills/superpowers" ] && echo "   SuperPowers   — $INSTALL_DIR/skills/superpowers/"
[ -d "$INSTALL_DIR/skills/browseract" ] && echo "   BrowserAct    — $INSTALL_DIR/skills/browseract/"
[ -d "$INSTALL_DIR/skills/superpowers" ] || [ -d "$INSTALL_DIR/skills/browseract" ] || echo "   (none — install with: git clone https://github.com/obra/superpowers.git $INSTALL_DIR/skills/superpowers)"
echo ""
echo " Update:"
echo "   $INSTALL_DIR/install.sh        # re-run to update"
echo "   OR: cd $INSTALL_DIR && git pull"
echo ""
