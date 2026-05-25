#!/usr/bin/env bash
# Arena Local Agent — Linux systemd-user installer.
# Создаёт user-юниты для bridge, MCP stream, MCP WS, Task Runner и Web Gateway.
# Запуск:    bash install_linux_service.sh
# Удаление:  bash install_linux_service.sh uninstall
set -euo pipefail

ROOT="$HOME/arena-agent"
BRIDGE_DIR="$HOME/arena-local-bridge"
UNIT_DIR="$HOME/.config/systemd/user"
TOKEN_FILE="$BRIDGE_DIR/token.txt"
PYTHON="$(command -v python3 || command -v python || true)"

ACTION="${1:-install}"

ALL_UNITS=(
  "arena-local-bridge.service"
  "arena-mcp-stream.service"
  "arena-mcp-ws.service"
  "arena-task-runner.service"
  "arena-web-gateway.service"
)

if [[ "$ACTION" == "uninstall" ]]; then
  for u in "${ALL_UNITS[@]}"; do
    systemctl --user disable --now "$u" 2>/dev/null || true
    rm -f "$UNIT_DIR/$u"
    rm -rf "$UNIT_DIR/${u}.d"
    echo "[OK] removed $u"
  done
  systemctl --user daemon-reload
  exit 0
fi

[[ -z "$PYTHON" ]] && { echo "ERR: python not found"; exit 1; }
mkdir -p "$BRIDGE_DIR" "$ROOT/scripts" "$ROOT/bin" "$UNIT_DIR"

# Токен
if [[ ! -f "$TOKEN_FILE" ]]; then
  python3 -c "import secrets,sys; sys.stdout.write(secrets.token_urlsafe(32))" > "$TOKEN_FILE"
  chmod 600 "$TOKEN_FILE"
  echo "[OK] generated token at $TOKEN_FILE"
fi

# PATH drop-in: гарантируем что bridge видит ~/arena-agent/bin
mkdir -p "$UNIT_DIR/arena-local-bridge.service.d"
cat > "$UNIT_DIR/arena-local-bridge.service.d/10-path.conf" <<EOF
[Service]
Environment=PATH=$HOME/arena-agent/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin
Environment=ARENA_AGENT_HOME=$HOME/arena-agent
EOF

# PATH drop-in для web-gateway
mkdir -p "$UNIT_DIR/arena-web-gateway.service.d"
cat > "$UNIT_DIR/arena-web-gateway.service.d/10-path.conf" <<EOF
[Service]
Environment=PATH=$HOME/arena-agent/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin
Environment=ARENA_AGENT_HOME=$HOME/arena-agent
EOF

write_unit() {
  local name="$1" desc="$2" exec="$3" extra="${4:-}"
  cat > "$UNIT_DIR/$name" <<EOF
[Unit]
Description=$desc
After=network.target

[Service]
Type=simple
ExecStart=$exec
Restart=on-failure
RestartSec=3
$extra

[Install]
WantedBy=default.target
EOF
}

# 1. Bridge
if [[ -f "$BRIDGE_DIR/local_bridge.py" ]]; then
  write_unit arena-local-bridge.service "Arena Local Bridge" \
    "$PYTHON $BRIDGE_DIR/local_bridge.py serve --root $HOME --profile owner-shell --allow-any-cwd --timeout 120 --max-timeout 1800 --max-output 10485760 --max-concurrent 3" \
    "Environment=ARENA_LOCAL_BRIDGE_TOKEN_FILE=$TOKEN_FILE"
  echo "[OK] arena-local-bridge.service unit created"
fi

# 2. MCP stream
if [[ -f "$ROOT/scripts/mcp_stream_server.py" ]]; then
  write_unit arena-mcp-stream.service "Arena MCP Streamable HTTP" \
    "$PYTHON $ROOT/scripts/mcp_stream_server.py --host 127.0.0.1 --port 8767"
  echo "[OK] arena-mcp-stream.service unit created"
fi

# 3. MCP WS
if [[ -f "$ROOT/scripts/mcp_ws_server.py" ]]; then
  write_unit arena-mcp-ws.service "Arena MCP WebSocket" \
    "$PYTHON $ROOT/scripts/mcp_ws_server.py --host 127.0.0.1 --port 8768"
  echo "[OK] arena-mcp-ws.service unit created"
fi

# 4. Task Runner
if [[ -f "$ROOT/bin/agentctl" ]]; then
  write_unit arena-task-runner.service "Arena Agent Task Runner" \
    "$PYTHON $ROOT/bin/agentctl task-watch --interval 5 --max 1" \
    "WorkingDirectory=$ROOT"$'\n'"NoNewPrivileges=yes"$'\n'"PrivateTmp=yes"$'\n'"ProtectSystem=full"$'\n'"ReadWritePaths=$HOME"
  echo "[OK] arena-task-runner.service unit created"
fi

# 5. Web Gateway
if [[ -f "$ROOT/bin/web_gateway.py" ]]; then
  write_unit arena-web-gateway.service "Arena Web Gateway (HTTP proxy для chat-платформ)" \
    "$PYTHON $ROOT/bin/web_gateway.py --host 127.0.0.1 --port 8769" \
    "Environment=ARENA_AGENT_HOME=$ROOT"$'\n'"Environment=ARENA_LOCAL_BRIDGE_TOKEN_FILE=$TOKEN_FILE"
  echo "[OK] arena-web-gateway.service unit created"
elif [[ -f "$ROOT/scripts/web_gateway.py" ]]; then
  write_unit arena-web-gateway.service "Arena Web Gateway (HTTP proxy для chat-платформ)" \
    "$PYTHON $ROOT/scripts/web_gateway.py --host 127.0.0.1 --port 8769" \
    "Environment=ARENA_AGENT_HOME=$ROOT"$'\n'"Environment=ARENA_LOCAL_BRIDGE_TOKEN_FILE=$TOKEN_FILE"
  echo "[OK] arena-web-gateway.service unit created"
fi

systemctl --user daemon-reload

for u in "${ALL_UNITS[@]}"; do
  if [[ -f "$UNIT_DIR/$u" ]]; then
    systemctl --user enable --now "$u" 2>/dev/null || true
    echo "[OK] enabled and started $u"
  fi
done

echo
echo "=== INSTALLATION COMPLETED SUCCESSFULLY ==="
echo "Status check:  agentctl sys status"
echo "Web TUI:       agentctl tui"
echo "Token:         cat $TOKEN_FILE"
echo "Funnel:        tailscale funnel --bg 8765"
echo "==========================================="
