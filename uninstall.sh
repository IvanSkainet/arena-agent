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
    if systemctl --user is-active arena-bridge >/dev/null 2>&1; then
        systemctl --user stop arena-bridge 2>/dev/null || true
        ok "systemd service stopped"
    fi
    if systemctl --user is-enabled arena-bridge >/dev/null 2>&1; then
        systemctl --user disable arena-bridge 2>/dev/null || true
        ok "systemd service disabled"
    fi
    # Remove service file
    SD_FILE="$HOME/.config/systemd/user/arena-bridge.service"
    if [ -f "$SD_FILE" ]; then
        rm -f "$SD_FILE"
        systemctl --user daemon-reload 2>/dev/null || true
        ok "systemd service file removed"
    fi
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
echo "[3/4] Removing bridge directory..."
if [ -d "$INSTALL_DIR" ]; then
    rm -rf "$INSTALL_DIR"
    ok "Directory removed: $INSTALL_DIR"
else
    warn "Directory not found: $INSTALL_DIR"
fi

echo ""
echo "[4/4] Removing old installation directories (if any)..."
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
