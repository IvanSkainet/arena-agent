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
    git pull --ff-only 2>/dev/null || { warn "git pull failed, using existing code"; }
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
    # Check if Tailscale is logged in (use || true to prevent set -e exit)
    TS_STATUS="$(tailscale status 2>&1 | head -1)" || TS_STATUS=""
    if echo "$TS_STATUS" | grep -qi "not logged in\|needs login\|stopped\|not connected" || [ -z "$TS_STATUS" ]; then
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
    else
        ok "Tailscale found and logged in — funnel available"
    fi
else
    info "Tailscale not found. Install it for internet access: https://tailscale.com"
fi

# --- 6b: SuperPowers (agentic skills framework) ---
SP_DIR="$INSTALL_DIR/skills/superpowers"
if [ -d "$SP_DIR" ]; then
    ok "SuperPowers already installed in skills/superpowers/"
else
    if ask "Install SuperPowers? (agentic TDD, debugging, planning skills for AI agents)"; then
        info "Cloning SuperPowers from GitHub..."
        git clone --depth 1 https://github.com/obra/superpowers.git "$SP_DIR" 2>/dev/null
        if [ -d "$SP_DIR/skills" ]; then
            ok "SuperPowers installed — 14 skills available (TDD, debugging, planning, etc.)"
        else
            warn "SuperPowers clone failed. You can install later:"
            echo "  git clone https://github.com/obra/superpowers.git $SP_DIR"
        fi
    else
        info "SuperPowers skipped. Install later with:"
        echo "  git clone https://github.com/obra/superpowers.git $SP_DIR"
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
                # Install skill file
                BA_SKILL_DIR="$INSTALL_DIR/skills/browser-act"
                mkdir -p "$BA_SKILL_DIR"
                if [ ! -f "$BA_SKILL_DIR/SKILL.md" ]; then
                    info "Downloading BrowserAct skill file..."
                    curl -fsSL "https://raw.githubusercontent.com/browser-act/skills/main/browser-act/SKILL.md" \
                        -o "$BA_SKILL_DIR/SKILL.md" 2>/dev/null || warn "Could not download skill file"
                fi
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
[ -d "$INSTALL_DIR/skills/browser-act" ] && echo "   BrowserAct    — $INSTALL_DIR/skills/browser-act/"
[ -d "$INSTALL_DIR/skills/superpowers" ] || [ -d "$INSTALL_DIR/skills/browser-act" ] || echo "   (none — install with: git clone https://github.com/obra/superpowers.git $INSTALL_DIR/skills/superpowers)"
echo ""
echo " Update:"
echo "   $INSTALL_DIR/install.sh        # re-run to update"
echo "   OR: cd $INSTALL_DIR && git pull"
echo ""
