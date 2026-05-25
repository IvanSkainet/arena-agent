#!/usr/bin/env bash
# Arena Local Agent — macOS launchd installer.
# Создаёт LaunchAgent plist'ы в ~/Library/LaunchAgents.
# Запуск:    bash install_macos_service.sh
# Удаление:  bash install_macos_service.sh uninstall
set -euo pipefail

ROOT="$HOME/arena-agent"
BRIDGE_DIR="$HOME/arena-local-bridge"
LA_DIR="$HOME/Library/LaunchAgents"
TOKEN_FILE="$BRIDGE_DIR/token.txt"
PYTHON="$(command -v python3 || command -v python || true)"

LABEL_BR="io.arena.local-bridge"
LABEL_ST="io.arena.mcp-stream"
LABEL_WS="io.arena.mcp-ws"

ACTION="${1:-install}"

if [[ "$ACTION" == "uninstall" ]]; then
  for L in $LABEL_BR $LABEL_ST $LABEL_WS; do
    launchctl unload "$LA_DIR/$L.plist" 2>/dev/null || true
    rm -f "$LA_DIR/$L.plist"
    echo "[OK] removed $L"
  done
  exit 0
fi

[[ -z "$PYTHON" ]] && { echo "ERR: python not found"; exit 1; }
mkdir -p "$BRIDGE_DIR" "$ROOT/scripts" "$ROOT/bin" "$LA_DIR"

if [[ ! -f "$TOKEN_FILE" ]]; then
  python3 -c "import secrets,sys; sys.stdout.write(secrets.token_urlsafe(32))" > "$TOKEN_FILE"
  chmod 600 "$TOKEN_FILE"
  echo "[OK] generated token at $TOKEN_FILE"
fi

write_plist() {
  local label="$1" script="$2" extra_args="$3" needs_token="$4"
  local env_block=""
  if [[ "$needs_token" == "1" ]]; then
    env_block="<key>EnvironmentVariables</key><dict>
      <key>ARENA_LOCAL_BRIDGE_TOKEN_FILE</key><string>$TOKEN_FILE</string>
      <key>ARENA_AGENT_HOME</key><string>$ROOT</string>
    </dict>"
  else
    env_block="<key>EnvironmentVariables</key><dict>
      <key>ARENA_AGENT_HOME</key><string>$ROOT</string>
    </dict>"
  fi
  cat > "$LA_DIR/$label.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON</string>
    <string>$script</string>
$(for a in $extra_args; do echo "    <string>$a</string>"; done)
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$ROOT/logs/$label.out.log</string>
  <key>StandardErrorPath</key><string>$ROOT/logs/$label.err.log</string>
  $env_block
</dict>
</plist>
EOF
  mkdir -p "$ROOT/logs"
  launchctl unload "$LA_DIR/$label.plist" 2>/dev/null || true
  launchctl load "$LA_DIR/$label.plist"
  echo "[OK] loaded $label"
}

[[ -f "$BRIDGE_DIR/local_bridge.py" ]] && write_plist "$LABEL_BR" "$BRIDGE_DIR/local_bridge.py" "serve --root $HOME --profile owner-shell --allow-any-cwd --timeout 120 --max-timeout 1800 --max-output 10485760 --max-concurrent 3" 1
[[ -f "$ROOT/scripts/mcp_stream_server.py" ]] && write_plist "$LABEL_ST" "$ROOT/scripts/mcp_stream_server.py" "--host 127.0.0.1 --port 8767" 0
[[ -f "$ROOT/scripts/mcp_ws_server.py" ]]     && write_plist "$LABEL_WS" "$ROOT/scripts/mcp_ws_server.py" "--host 127.0.0.1 --port 8768" 0

echo
echo "Status: launchctl list | grep io.arena"
echo "Token:  cat $TOKEN_FILE"
