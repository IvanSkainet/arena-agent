#!/usr/bin/env bash
# ============================================================
#  Arena Unified Bridge — Universal Installer (Linux/macOS)
#  Downloads the latest version from GitHub, sets up everything
#  in one directory. No scattered files across home.
#  Run:  curl -fsSL https://raw.githubusercontent.com/IvanSkainet/arena-agent/master/install.sh | bash
# ============================================================
# If invoked as `sh install.sh`, re-exec under bash. The installer intentionally
# uses bash features (`[[ ... ]]`, arrays/pipefail-compatible semantics).
if [ -z "${BASH_VERSION:-}" ]; then
    exec bash "$0" "$@"
fi
set -euo pipefail

REPO="IvanSkainet/arena-agent"
# Default to `master` (stable release branch). Override with ARENA_BRANCH.
# NOTE: the updater below never force-checks-out a different branch on
# existing installations - it only ff-pulls the CURRENT branch.
BRANCH="${ARENA_BRANCH:-master}"
INSTALL_DIR="${ARENA_INSTALL_DIR:-${HOME:-$(pwd)}/arena-bridge}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${ARENA_PORT:-8765}"
PROFILE="owner-shell"

ok()   { echo -e "\033[32m[OK]\033[0m $*"; }
warn() { echo -e "\033[33m[WARN]\033[0m $*"; }
err()  { echo -e "\033[31m[ERROR]\033[0m $*"; }
info() { echo -e "\033[34m[INFO]\033[0m $*"; }
ask()  { echo -en "\033[36m[?] $* [y/N]: \033[0m"; read -r REPLY; [[ "$REPLY" =~ ^[Yy]$ ]]; }

# Compare two semver-ish versions X.Y.Z. Returns 0 (true) if v1 < v2, 1 otherwise.
_arena_version_lt() {
    local v1="$1" v2="$2"
    local i1 i2
    # Strip leading non-digit (e.g. "v3.1.5" -> "3.1.5") and split on "."
    v1="${v1#v}"; v2="${v2#v}"
    IFS="." read -ra i1 <<< "$v1"
    IFS="." read -ra i2 <<< "$v2"
    local n=${#i1[@]}; [ ${#i2[@]} -gt $n ] && n=${#i2[@]}
    local idx a b
    for ((idx=0; idx<n; idx++)); do
        a="${i1[idx]:-0}"; b="${i2[idx]:-0}"
        # Strip any suffix like "-rc1" by taking only the leading integer
        a="${a%%[^0-9]*}"; b="${b%%[^0-9]*}"
        [ -z "$a" ] && a=0; [ -z "$b" ] && b=0
        if [ "$a" -lt "$b" ]; then return 0; fi
        if [ "$a" -gt "$b" ]; then return 1; fi
    done
    return 1
}

echo ""
echo "========================================"
echo " Arena Unified Bridge — Installer"
echo "========================================"
echo ""

cat <<EOF
========================================
 TRANSPARENCY NOTICE - BACKGROUND SERVICE
========================================
 Arena Unified Bridge is a local automation server.
 This installer will register a visible background service/agent when possible:

   Linux:  systemd user service  arena-bridge.service
   macOS:  launchd agent         com.arena.bridge
   Local:  http://127.0.0.1:$PORT

 You may see python/unified_bridge.py, ydotoold, tailscale, or cloudflared
 processes depending on enabled features. This is expected and is NOT stealth
 software. It lets your AI tools keep talking to this machine after this
 terminal is closed.

 To inspect later:
   systemctl --user status arena-bridge.service   # Linux
   launchctl print gui/\$UID/com.arena.bridge      # macOS

 To remove later:
   ./uninstall.sh
EOF

if [ "${ARENA_ACCEPT_BACKGROUND:-}" != "1" ] && [ "${ARENA_ASSUME_YES:-}" != "1" ]; then
    if ! ask "Continue and install/update the background service?"; then
        warn "Installation aborted by user. No service/agent was installed by this run."
        warn "Set ARENA_ACCEPT_BACKGROUND=1 to skip this prompt in automation."
        exit 0
    fi
fi

echo ""

# --- Step 1: Download or update the repo ---
if [ -d "$INSTALL_DIR/.git" ]; then
    cd "$INSTALL_DIR"
    CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
    info "Existing installation found at $INSTALL_DIR (branch: $CURRENT_BRANCH)"

    # Find a Python interpreter for the version probe. The full Python search
    # happens later (Step 2); here we just need any python3 to call _arena_helper.
    _ARENA_PROBE_PY=""
    for _cand in python3.14 python3.13 python3.12 python3.11 python3.10 python3 python; do
        if command -v "$_cand" >/dev/null 2>&1; then _ARENA_PROBE_PY="$(command -v "$_cand")"; break; fi
    done

    # Read locally-installed version (canonical source: arena/constants.py).
    LOCAL_VERSION=""
    HELPER="$INSTALL_DIR/_arena_helper.py"
    if [ -n "$_ARENA_PROBE_PY" ] && [ -f "$HELPER" ]; then
        LOCAL_VERSION="$("$_ARENA_PROBE_PY" "$HELPER" version 2>/dev/null || true)"
    fi
    [ -z "$LOCAL_VERSION" ] && LOCAL_VERSION="unknown"

    # Fetch current branch from origin. DO NOT switch branches - that would
    # silently downgrade users who pinned themselves to a release branch.
    if ! git fetch origin "$CURRENT_BRANCH" --depth 1 2>/dev/null; then
        warn "git fetch origin/$CURRENT_BRANCH failed (offline?). Continuing with local code."
    fi

    # Inspect the remote tip version without checking it out.
    # Read `arena/constants.py` from git and extract the VERSION
    # line. We do NOT use _arena_helper.py for this because the
    # helper resolves Path(__file__).parent to find arena/constants.py
    # next to it, and a temp-file copy would not have that neighbour.
    REMOTE_VERSION="unknown"
    REMOTE_CONSTANTS="$(git show "origin/$CURRENT_BRANCH:arena/constants.py" 2>/dev/null || true)"
    if [ -n "$REMOTE_CONSTANTS" ]; then
        # Pick the VERSION = "x.y.z" line, then cut between the double quotes.
        VERSION_LINE="$(printf '%s\n' "$REMOTE_CONSTANTS" | grep -E '^VERSION[[:space:]]*=' | head -1)"
        if [ -n "$VERSION_LINE" ]; then
            REMOTE_VERSION="$(printf '%s\n' "$VERSION_LINE" | cut -d\" -f2)"
        fi
    fi
    [ -z "$REMOTE_VERSION" ] && REMOTE_VERSION="unknown"

    info "Local version:  v$LOCAL_VERSION"
    info "Remote version: v$REMOTE_VERSION (origin/$CURRENT_BRANCH)"

    # Decide whether to update.
    SHOULD_UPDATE="no"
    if [ "$REMOTE_VERSION" = "unknown" ]; then
        warn "Could not determine remote version. Keeping local v$LOCAL_VERSION."
    elif [ "$LOCAL_VERSION" = "unknown" ]; then
        warn "Could not determine local version. Offering update to v$REMOTE_VERSION."
        SHOULD_UPDATE="ask"
    elif [ "$LOCAL_VERSION" = "$REMOTE_VERSION" ]; then
        ok "Already up to date (v$LOCAL_VERSION). No update needed."
    elif _arena_version_lt "$LOCAL_VERSION" "$REMOTE_VERSION"; then
        SHOULD_UPDATE="ask"
    else
        # Local version is NEWER than remote. This happens when the user is on
        # a development branch or has local commits. NEVER downgrade silently.
        ok "Local v$LOCAL_VERSION is newer than remote v$REMOTE_VERSION. Keeping local."
        info "To downgrade to origin/$CURRENT_BRANCH, run: cd \"$INSTALL_DIR\" && git reset --hard origin/$CURRENT_BRANCH"
    fi

    if [ "$SHOULD_UPDATE" = "ask" ]; then
        if [ "${ARENA_ASSUME_YES:-}" = "1" ] || [ "${ARENA_AUTO_UPDATE:-}" = "1" ]; then
            ok "Auto-updating to v$REMOTE_VERSION (ARENA_ASSUME_YES=1)"
            SHOULD_UPDATE="yes"
        elif ask "Update local v$LOCAL_VERSION -> v$REMOTE_VERSION from origin/$CURRENT_BRANCH?"; then
            SHOULD_UPDATE="yes"
        else
            warn "Update declined. Keeping local v$LOCAL_VERSION."
        fi
    fi

    if [ "$SHOULD_UPDATE" = "yes" ]; then
        # Fast-forward only. Never reset --hard, never switch branches, never
        # discard uncommitted work. If ff fails, the user resolves manually.
        if git merge --ff-only "origin/$CURRENT_BRANCH" 2>/dev/null; then
            ok "Updated to v$REMOTE_VERSION (origin/$CURRENT_BRANCH)"
        else
            warn "Fast-forward update failed (diverged branches or local commits)."
            warn "Your local changes are preserved. Resolve manually:"
            warn "  cd \"$INSTALL_DIR\" && git status && git log --oneline -5"
        fi
    fi
elif [ -f "$SCRIPT_DIR/unified_bridge.py" ] && [ -d "$SCRIPT_DIR/arena" ]; then
    info "Installing from local source: $SCRIPT_DIR -> $INSTALL_DIR"
    mkdir -p "$INSTALL_DIR"
    if command -v rsync >/dev/null 2>&1; then
        rsync -a           --exclude '.git' --exclude '__pycache__' --exclude '.pytest_cache'           --exclude 'token.txt' --exclude 'audit.jsonl' --exclude 'requests.jsonl' --exclude 'bridge.log'           --exclude 'queue/running/' --exclude 'queue/done/' --exclude 'queue/failed/'           "$SCRIPT_DIR/" "$INSTALL_DIR/"
    else
        (cd "$SCRIPT_DIR" && tar --exclude='.git' --exclude='__pycache__' --exclude='.pytest_cache' -cf - .) | (cd "$INSTALL_DIR" && tar -xf -)
    fi
    cd "$INSTALL_DIR"
else
    info "Downloading Arena Unified Bridge from GitHub (branch: $BRANCH) ..."
    git clone --depth 1 -b "$BRANCH" "https://github.com/$REPO.git" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# --- Read version from the bridge itself ---
BRIDGE_PY="$INSTALL_DIR/unified_bridge.py"
if [ ! -f "$BRIDGE_PY" ]; then
    err "unified_bridge.py not found in $INSTALL_DIR"
    exit 1
fi
VERSION=""
VERSION_PY=""
for cand in python3.14 python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then VERSION_PY="$(command -v "$cand")"; break; fi
done
if [ -n "$VERSION_PY" ] && [ -f "$INSTALL_DIR/_arena_helper.py" ]; then
    VERSION="$($VERSION_PY "$INSTALL_DIR/_arena_helper.py" version 2>/dev/null || true)"
fi
if [ -z "$VERSION" ]; then
    VERSION="unknown"
fi
ok "Bridge v$VERSION downloaded"

# --- Step 1b: Add Homebrew paths for macOS Apple Silicon ---
for brew_prefix in /opt/homebrew /usr/local; do
    if [ -d "$brew_prefix/bin" ]; then
        PATH="$brew_prefix/bin:$PATH"
    fi
done

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
if [ -f "$INSTALL_DIR/requirements.txt" ]; then
    "$PY" -m pip install -r "$INSTALL_DIR/requirements.txt" --quiet 2>/dev/null || true
else
    "$PY" -m pip install aiohttp psutil websockets --quiet 2>/dev/null || true
fi
ok "Python packages ready"

# --- Step 4: Create subdirectories (all inside INSTALL_DIR) ---
info "Creating directory structure..."
for d in "$INSTALL_DIR/memory" "$INSTALL_DIR/missions" \
         "$INSTALL_DIR/queue/inbox" "$INSTALL_DIR/queue/running" "$INSTALL_DIR/queue/done" "$INSTALL_DIR/queue/failed" \
         "$INSTALL_DIR/reports" "$INSTALL_DIR/logs" \
         "$INSTALL_DIR/hooks/pre_skill.d" "$INSTALL_DIR/hooks/post_skill.d" \
         "$INSTALL_DIR/skills" "$INSTALL_DIR/subagents" "$INSTALL_DIR/mcp" \
         "$INSTALL_DIR/projects" "$INSTALL_DIR/scripts" "$INSTALL_DIR/bin"; do
    mkdir -p "$d"
done
ok "Directories ready"

# --- Step 4a: Substitute paths in MCP registry.json ---
REGISTRY_FILE="$INSTALL_DIR/mcp/registry.json"
if [ -f "$REGISTRY_FILE" ]; then
    sed -i "s|\${ARENA_AGENT_HOME}|$INSTALL_DIR|g" "$REGISTRY_FILE" 2>/dev/null || true
fi

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
except Exception: pass
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
    # Tailscale is NOT installed. Offer to install it (with explicit consent),
    # because Tailscale Funnel is the recommended way to expose the bridge to
    # the internet. We use the official Tailscale install script which handles
    # apt/dnf/pacman/etc. automatically.
    info "Tailscale not found. Tailscale Funnel is the recommended way to expose"
    info "the bridge to the internet (real HTTPS via Let's Encrypt, no port-forward)."
    info ""
    info "Installing Tailscale requires sudo and will add a system package."
    info "After install, you will need to run 'tailscale login' (opens a browser URL)"
    info "and then 'tailscale funnel --bg $PORT' to publish the bridge."
    info ""
    if [ "${ARENA_ASSUME_YES:-}" = "1" ] || ask "Install Tailscale now via official script?"; then
        info "Running official Tailscale install script (requires sudo)..."
        if command -v curl >/dev/null 2>&1; then
            curl -fsSL https://tailscale.com/install.sh | sudo sh 2>&1
        elif command -v wget >/dev/null 2>&1; then
            wget -qO- https://tailscale.com/install.sh | sudo sh 2>&1
        else
            warn "Neither curl nor wget found; cannot run Tailscale install script."
            warn "Install manually: https://tailscale.com/download"
        fi
        if command -v tailscale >/dev/null 2>&1; then
            ok "Tailscale installed. Next steps:"
            echo "  1. Log in:           sudo tailscale login"
            echo "     (opens a URL in your browser - sign in with Google/GitHub/etc.)"
            echo "  2. Publish bridge:   sudo tailscale funnel --bg $PORT"
            echo "     (exposes http://127.0.0.1:$PORT to the internet via HTTPS)"
            echo "  3. Your public URL will look like: https://$(hostname).tail-XXXXX.ts.net"
            echo ""
            if ask "Run 'tailscale login' now? (requires sudo)"; then
                sudo tailscale login 2>&1 && ok "Tailscale login initiated - follow the URL in output" || warn "Tailscale login failed"
            else
                info "You can log in later: sudo tailscale login"
            fi
        else
            warn "Tailscale install may have failed. Install manually:"
            echo "  https://tailscale.com/download"
        fi
    else
        info "Tailscale install skipped. To set up later:"
        echo "  curl -fsSL https://tailscale.com/install.sh | sh"
        echo "  sudo tailscale login"
        echo "  sudo tailscale funnel --bg $PORT"
        info ""
        info "Alternative: cloudflared (below) also exposes the bridge without Tailscale."
    fi
fi

# --- 6a-bis: cloudflared (optional Cloudflare Quick Tunnel) ---
# Not bundled in the repo (it's a ~40 MB binary). Fetched on demand here so the
# repository stays lightweight. The bridge looks for it on PATH first, then in
# the install directory, so either source works.
CF_BIN="$INSTALL_DIR/cloudflared"
CF_CURRENT=""
if command -v cloudflared >/dev/null 2>&1; then
    CF_CURRENT="$(cloudflared --version 2>/dev/null || true)"
    ok "cloudflared found on PATH${CF_CURRENT:+ — $CF_CURRENT}"
elif [ -f "$CF_BIN" ]; then
    CF_CURRENT="$($CF_BIN --version 2>/dev/null || true)"
    ok "cloudflared present in install directory${CF_CURRENT:+ — $CF_CURRENT}"
else
    UNAME_S="$(uname -s)"
    UNAME_M="$(uname -m)"
    CF_URL=""
    case "$UNAME_S" in
        Linux)
            case "$UNAME_M" in
                x86_64|amd64) CF_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64" ;;
                aarch64|arm64) CF_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64" ;;
                armv7l|armhf) CF_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm" ;;
            esac
            ;;
        Darwin)
            # macOS ships cloudflared as a .tgz; Homebrew is the simplest path.
            info "cloudflared not found. On macOS install it with: brew install cloudflared"
            ;;
    esac
    if [ -n "$CF_URL" ]; then
        if [ "${ARENA_ASSUME_YES:-}" = "1" ] || ask "Download cloudflared (~40 MB) for Cloudflare Quick Tunnels? (Tailscale is the recommended option)"; then
            info "Downloading cloudflared for $UNAME_S/$UNAME_M ..."
            if command -v curl >/dev/null 2>&1; then
                curl -fsSL "$CF_URL" -o "$CF_BIN" && chmod +x "$CF_BIN" && ok "cloudflared installed at $CF_BIN" || warn "cloudflared download failed (you can install it later)"
            elif command -v wget >/dev/null 2>&1; then
                wget -qO "$CF_BIN" "$CF_URL" && chmod +x "$CF_BIN" && ok "cloudflared installed at $CF_BIN" || warn "cloudflared download failed (you can install it later)"
            else
                warn "Neither curl nor wget found; skipping cloudflared download"
            fi
        else
            info "cloudflared skipped. Re-run the installer or download it later from https://github.com/cloudflare/cloudflared/releases/latest"
        fi
    fi
fi
if [ -n "${CF_CURRENT:-}" ]; then
    CF_LATEST=""
    if command -v curl >/dev/null 2>&1; then
        CF_LATEST="$(curl -fsSL --max-time 20 https://api.github.com/repos/cloudflare/cloudflared/releases/latest 2>/dev/null | "$PY" -c 'import json,sys; print(json.load(sys.stdin).get("tag_name", ""))' 2>/dev/null || true)"
    fi
    [ -n "$CF_LATEST" ] && info "cloudflared latest release: $CF_LATEST" || warn "Could not verify cloudflared latest release (network/GitHub unavailable)"
fi

# --- 6b: SuperPowers (agentic skills framework) ---
SP_DIR="$INSTALL_DIR/skills/superpowers/skills"
if [ -d "$SP_DIR" ]; then
    SP_COUNT=$(ls -1 "$SP_DIR" 2>/dev/null | wc -l)
    ok "SuperPowers already installed — $SP_COUNT skills in skills/superpowers/skills/"
    if [ -d "$INSTALL_DIR/skills/superpowers/.git" ]; then
        SP_REV="$(git -C "$INSTALL_DIR/skills/superpowers" rev-parse --short HEAD 2>/dev/null || true)"
        [ -n "$SP_REV" ] && info "SuperPowers revision: $SP_REV"
        info "Checking SuperPowers updates..."
        git -C "$INSTALL_DIR/skills/superpowers" pull --ff-only --quiet 2>/dev/null && ok "SuperPowers is up to date or fast-forwarded" || warn "SuperPowers update check failed/skipped"
    fi
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
    BA_VERSION="$(browser-act --version 2>/dev/null || echo 'installed')"
    ok "BrowserAct already installed: $BA_VERSION"
    if command -v uv >/dev/null 2>&1; then
        info "Checking BrowserAct updates via uv..."
        uv tool upgrade browser-act-cli >/dev/null 2>&1 && ok "BrowserAct is up to date or upgraded" || warn "BrowserAct update check failed/skipped"
    fi
else
    # Check for uv
    if command -v uv >/dev/null 2>&1; then
        info "BrowserAct installs GLOBALLY via `uv tool` (in ~/.local/bin or equivalent),"
        info "NOT inside the bridge directory. The bridge calls `browser-act` via PATH,"
        info "so a global install is required for it to work."
        if ask "Install BrowserAct globally via uv? (browser automation CLI — browse, click, forms, CAPTCHAs)"; then
            info "Installing BrowserAct via uv tool (global, outside bridge dir)..."
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
            info "Checking Camoufox browser files..."
            $BA_PYTHON -m camoufox fetch >/dev/null 2>&1 && ok "Camoufox browser files are present/current" || warn "Camoufox fetch/update failed or skipped"
        else
            info "Camoufox downloads ~300MB to a SYSTEM CACHE directory"
            info "(typically ~/.cache/camoufox on Linux), NOT inside the bridge directory."
            info "This is required by the camoufox Python package and cannot be redirected."
            if ask "Download Camoufox stealth browser? (~300MB to system cache, enables BrowserAct stealth mode)"; then
                info "Downloading Camoufox browser binary to system cache..."
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

    # v2.5.1: Clean up legacy service files from old arena-agent package.
    # The unified bridge now includes task-runner internally, so these
    # separate services are obsolete and cause crash loops if left behind.
    for _legacy_svc in arena-task-runner arena-local-bridge arena-mcp-stream arena-mcp-ws arena-web-gateway; do
        if [ -f "$SD_DIR/${_legacy_svc}.service" ]; then
            info "Removing legacy service: ${_legacy_svc}.service"
            systemctl --user stop "${_legacy_svc}.service" 2>/dev/null || true
            systemctl --user disable "${_legacy_svc}.service" 2>/dev/null || true
            rm -f "$SD_DIR/${_legacy_svc}.service"
            # Also clean any override dirs
            rm -rf "$SD_DIR/${_legacy_svc}.service.d"
        fi
    done
    systemctl --user daemon-reload 2>/dev/null || true

    ESCAPED_BRIDGE_PY=$(systemd_escape "$BRIDGE_PY")
    ESCAPED_TOKEN_FILE=$(systemd_escape "$TOKEN_FILE")
    ESCAPED_INSTALL_DIR=$(systemd_escape "$INSTALL_DIR")

    # Get the actual UID for the service file — use numeric UID instead of %U
    # because %U may not be expanded correctly in some systemd versions
    ACTUAL_UID=$(id -u)

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
Environment=HOME=${HOME}
Environment=XDG_RUNTIME_DIR=/run/user/${ACTUAL_UID}
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/${ACTUAL_UID}/bus
EOF
    # Auto-detect display environment — only set if actually available
    if [ -n "$DISPLAY" ]; then
        echo "Environment=DISPLAY=${DISPLAY}" >> "$SD_DIR/arena-bridge.service"
    elif [ -d "/tmp/.X11-unix" ]; then
        echo "Environment=DISPLAY=:0" >> "$SD_DIR/arena-bridge.service"
    fi
    if [ -n "$WAYLAND_DISPLAY" ]; then
        echo "Environment=WAYLAND_DISPLAY=${WAYLAND_DISPLAY}" >> "$SD_DIR/arena-bridge.service"
    elif [ -S "${XDG_RUNTIME_DIR:-/run/user/${ACTUAL_UID}}/wayland-0" ]; then
        echo "Environment=WAYLAND_DISPLAY=wayland-0" >> "$SD_DIR/arena-bridge.service"
    fi
    if [ -n "$XDG_SESSION_TYPE" ]; then
        echo "Environment=XDG_SESSION_TYPE=${XDG_SESSION_TYPE}" >> "$SD_DIR/arena-bridge.service"
    fi
    if [ -n "$XDG_CURRENT_DESKTOP" ]; then
        echo "Environment=XDG_CURRENT_DESKTOP=${XDG_CURRENT_DESKTOP}" >> "$SD_DIR/arena-bridge.service"
    fi
    if [ -n "$DESKTOP_SESSION" ]; then
        echo "Environment=DESKTOP_SESSION=${DESKTOP_SESSION}" >> "$SD_DIR/arena-bridge.service"
    fi
    # Auto-detect Chromium library path
    CHROMIUM_LIB=""
    for libdir in /usr/lib/chromium /usr/lib64/chromium /usr/lib/chromium-browser /usr/lib64/chromium-browser /snap/chromium/current/usr/lib; do
        if [ -d "$libdir" ]; then CHROMIUM_LIB="$libdir"; break; fi
    done
    if [ -n "$CHROMIUM_LIB" ]; then
        echo "Environment=LD_LIBRARY_PATH=${CHROMIUM_LIB}" >> "$SD_DIR/arena-bridge.service"
    fi
    cat >> "$SD_DIR/arena-bridge.service" << EOF

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
    if command -v ss >/dev/null 2>&1; then
        PIDS="$(ss -tlnp "sport = :$PORT" 2>/dev/null | grep -oP 'pid=\K[0-9]+' || true)"
    elif command -v lsof >/dev/null 2>&1; then
        PIDS="$(lsof -ti :"$PORT" 2>/dev/null || true)"
    else
        PIDS=""
    fi
    [ -n "$PIDS" ] && kill $PIDS 2>/dev/null || true
    # v2.1.0: Rotate log if over 10MB before starting (prevents disk fill)
    LOG_FILE="$INSTALL_DIR/logs/bridge.log"
    if [ -f "$LOG_FILE" ] && [ "$(stat -f%z "$LOG_FILE" 2>/dev/null || stat -c%s "$LOG_FILE" 2>/dev/null || echo 0)" -gt 10485760 ]; then
        [ -f "$LOG_FILE.2" ] && rm -f "$LOG_FILE.2"
        [ -f "$LOG_FILE.1" ] && mv -f "$LOG_FILE.1" "$LOG_FILE.2"
        mv -f "$LOG_FILE" "$LOG_FILE.1"
    fi
    ARENA_TOKEN_FILE="$TOKEN_FILE" nohup "$PY" -u "$BRIDGE_PY" serve --root "$HOME" --profile "$PROFILE" --port "$PORT" \
        >> "$INSTALL_DIR/logs/bridge.log" 2>&1 &
    ok "Bridge started with nohup (won't survive reboot)"
fi

# --- Step 8: Wait for bridge to come up ---
info "Waiting for bridge to start..."
for i in $(seq 1 20); do
    if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
        ok "Bridge is healthy. v${VERSION}"
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
except Exception: pass
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
except Exception: pass
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
    if command -v tailscale >/dev/null 2>&1; then
        if tailscale funnel status 2>/dev/null | grep -Eiq 'Funnel on|proxy http'; then
            ok "Tailscale Funnel appears active for this machine."
        else
            info "Tailscale Funnel does not appear to be enabled yet."
            echo "   To publish the bridge: tailscale funnel --bg $PORT"
        fi
    fi
fi
echo ""
echo " Background service/agent:"
if [ "$OS" = "Linux" ]; then
    echo "   Name: arena-bridge.service (systemd --user)"
    echo "   This is expected. It keeps the bridge available after this terminal closes."
    echo "   To remove: $INSTALL_DIR/uninstall.sh"
    echo ""
    echo " Manage:"
    echo "   systemctl --user status   arena-bridge"
    echo "   systemctl --user restart  arena-bridge"
    echo "   systemctl --user stop     arena-bridge"
    echo "   journalctl --user -u arena-bridge -f"
elif [ "$OS" = "Darwin" ]; then
    echo "   Name: com.arena.bridge (launchd)"
    echo "   This is expected. It keeps the bridge available after this terminal closes."
    echo "   To remove: $INSTALL_DIR/uninstall.sh"
    echo ""
    echo " Manage:"
    echo "   launchctl print gui/\$UID/com.arena.bridge"
    echo "   launchctl kickstart -k gui/\$UID/com.arena.bridge"
else
    echo "   Started with nohup for this user session."
    echo "   To remove: $INSTALL_DIR/uninstall.sh"
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
