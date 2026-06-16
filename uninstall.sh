#!/usr/bin/env bash
# ============================================================
#  Arena Unified Bridge — Uninstaller (Linux/macOS)
#  Stops services, removes systemd/launchd entries, deletes files.
#  Run:  ./uninstall.sh
# ============================================================
set -euo pipefail

INSTALL_DIR="${ARENA_INSTALL_DIR:-$HOME/arena-bridge}"
PORT="${ARENA_PORT:-8765}"

ok()   { echo -e "\033[32m[OK]\033[0m $*"; }
warn() { echo -e "\033[33m[WARN]\033[0m $*"; }
err()  { echo -e "\033[31m[ERROR]\033[0m $*"; }

echo ""
echo "========================================"
echo " Arena Unified Bridge — Uninstaller"
echo "========================================"
echo ""
echo " This will completely remove Arena Unified Bridge:"
echo "   - Stop and remove systemd/launchd service"
echo "   - Kill all bridge processes on port $PORT"
echo "   - Delete the entire directory: $INSTALL_DIR"
echo ""
read -rp "$(echo -e '\033[31m[?] Are you sure? This cannot be undone. [y/N]: \033[0m')" CONFIRM
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

echo ""
echo "[1/4] Stopping bridge processes..."

OS="$(uname -s)"

# --- Stop and remove systemd service ---
if [ "$OS" = "Linux" ] && command -v systemctl >/dev/null 2>&1; then
    # v2.5.1: Clean up ALL arena-related services, including legacy ones
    for SVC in arena-bridge arena-task-runner arena-local-bridge arena-mcp-stream arena-mcp-ws arena-web-gateway; do
        if systemctl --user is-active "$SVC" >/dev/null 2>&1; then
            systemctl --user stop "$SVC" 2>/dev/null || true
            ok "systemd service $SVC stopped"
        fi
        if systemctl --user is-enabled "$SVC" >/dev/null 2>&1; then
            systemctl --user disable "$SVC" 2>/dev/null || true
            ok "systemd service $SVC disabled"
        fi
        # Remove service file and override dirs
        SD_FILE="$HOME/.config/systemd/user/${SVC}.service"
        if [ -f "$SD_FILE" ]; then
            rm -f "$SD_FILE"
            ok "systemd service file ${SVC}.service removed"
        fi
        if [ -d "${SD_FILE}.d" ]; then
            rm -rf "${SD_FILE}.d"
            ok "systemd service override dir ${SVC}.service.d removed"
        fi
    done
    systemctl --user daemon-reload 2>/dev/null || true
fi

# --- Stop and remove launchd service ---
if [ "$OS" = "Darwin" ]; then
    PLIST="$HOME/Library/LaunchAgents/com.arena.bridge.plist"
    if [ -f "$PLIST" ]; then
        launchctl unload "$PLIST" 2>/dev/null || true
        rm -f "$PLIST"
        ok "launchd service removed"
    fi
fi

# --- Kill processes on bridge port ---
PIDS="$(lsof -ti :"$PORT" 2>/dev/null || true)"
if [ -n "$PIDS" ]; then
    kill $PIDS 2>/dev/null || true
    sleep 1
    # Force kill if still running
    PIDS="$(lsof -ti :"$PORT" 2>/dev/null || true)"
    if [ -n "$PIDS" ]; then
        kill -9 $PIDS 2>/dev/null || true
    fi
    ok "Bridge processes killed"
else
    ok "No bridge processes found"
fi

echo ""
echo "[2/4] Stopping Tailscale Funnel (if active)..."
if command -v tailscale >/dev/null 2>&1; then
    tailscale funnel off 2>/dev/null || true
    ok "Tailscale funnel stopped"
else
    warn "Tailscale not found"
fi

echo ""
echo "[3/5] Stopping Cloudflared quick tunnels (if active)..."
CF_PIDS="$(pgrep -f 'cloudflared.*tunnel.*--url.*127.0.0.1' 2>/dev/null || true)"
if [ -n "$CF_PIDS" ]; then
    kill $CF_PIDS 2>/dev/null || true
    sleep 1
    CF_PIDS="$(pgrep -f 'cloudflared.*tunnel.*--url.*127.0.0.1' 2>/dev/null || true)"
    [ -n "$CF_PIDS" ] && kill -9 $CF_PIDS 2>/dev/null || true
    ok "cloudflared quick tunnel processes stopped"
else
    ok "No cloudflared quick tunnel processes found"
fi
if [ -f "$INSTALL_DIR/cloudflared" ] || [ -f "$INSTALL_DIR/cloudflared.exe" ]; then
    rm -f "$INSTALL_DIR/cloudflared" "$INSTALL_DIR/cloudflared.exe" 2>/dev/null || true
    ok "Bundled cloudflared binary removed"
fi

echo ""
echo "[4/5] Removing bridge directory..."
if [ -d "$INSTALL_DIR" ]; then
    rm -rf "$INSTALL_DIR"
    ok "Directory removed: $INSTALL_DIR"
else
    warn "Directory not found: $INSTALL_DIR"
fi

echo ""
echo "[5/5] Removing old installation directories (if any)..."
for OLD_DIR in "$HOME/.arena-local-bridge" "$HOME/.arena-agent"; do
    if [ -d "$OLD_DIR" ]; then
        rm -rf "$OLD_DIR"
        ok "Removed $OLD_DIR"
    fi
done

echo ""
echo "========================================"
echo " Uninstallation Complete"
echo "========================================"
echo ""
echo " Arena Unified Bridge has been removed."
echo ""
