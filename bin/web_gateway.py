#!/usr/bin/env python3
"""web_gateway.py — простой HTTP-эндпоинт для интеграции в chat-платформы.

Идея (вдохновлено MCP-SuperAssistant без Chrome extension): любой клиент
(ChatGPT custom GPT, Gemini Gem, обычный curl) может дёргать один URL и
получать ответ от Arena Agent — без знания протокола MCP.

Endpoints:
  GET  /             — info JSON
  GET  /tools        — список доступных команд (whitelist)
  POST /run          — body: {"command": "agentctl ...", "timeout": 60}
                        Returns: {"ok": bool, "stdout": "...", "stderr": "...", "exit": int}
  POST /tool         — body: {"name": "browser.search", "arguments": {...}}
                        Прокси в MCP Streamable HTTP (:8767/mcp)

Защита: токен в header X-Arena-Token (то же значение что bridge token).
Whitelist команд (если задан) ограничивает /run только разрешёнными префиксами.

Запуск: python3 web_gateway.py --host 127.0.0.1 --port 8769
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(os.environ.get("ARENA_AGENT_HOME", str(Path.home() / "arena-bridge"))).expanduser()
TOKEN = os.environ.get("ARENA_LOCAL_BRIDGE_TOKEN", "")
TOKEN_FILE = Path.home() / "arena-local-bridge" / "token.txt"
if not TOKEN and TOKEN_FILE.exists():
    TOKEN = TOKEN_FILE.read_text().strip()

MCP_URL = "http://127.0.0.1:8767/mcp"
WHITELIST_PREFIXES = (
    "agentctl skill ", "agentctl mem ", "agentctl recall ",
    "agentctl sub list", "agentctl sub show", "agentctl sub spawn",
    "agentctl browser py-", "agentctl agents ", "agentctl mission list",
    "agentctl sys status", "agentctl hooks list", "agentctl report ",
)

VERSION = "0.1.0"


def _post_mcp(payload: dict, timeout: int = 60) -> dict:
    req = urllib.request.Request(MCP_URL, data=json.dumps(payload).encode(),
                                  headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _run_shell(cmd: str, timeout: int = 60) -> dict:
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return {"ok": p.returncode == 0, "exit": p.returncode,
                "stdout": p.stdout[-20000:], "stderr": p.stderr[-3000:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "exit": -1, "stdout": "", "stderr": "timeout"}
    except Exception as e:
        return {"ok": False, "exit": -2, "stdout": "", "stderr": str(e)}


def _allowed(cmd: str) -> bool:
    return any(cmd.startswith(p) for p in WHITELIST_PREFIXES)


class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        sys.stderr.write(f"{self.address_string()} - - [{self.log_date_time_string()}] {fmt % a}\n")

    def _check_auth(self) -> bool:
        if not TOKEN:
            return True  # no token configured => open (dev mode)
        h = self.headers.get("X-Arena-Token") or self.headers.get("Authorization", "").replace("Bearer ", "")
        return h == TOKEN

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Arena-Token, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204); self.end_headers()

    def do_GET(self):
        if self.path == "/":
            return self._json({"ok": True, "service": "arena-web-gateway", "version": VERSION,
                                "endpoints": ["/", "/tools", "/run (POST)", "/tool (POST)"],
                                "mcp_proxy": MCP_URL, "auth_required": bool(TOKEN)})
        if self.path == "/tools":
            if not self._check_auth(): return self._json({"ok": False, "error": "unauthorized"}, 401)
            try:
                mcp_tools = _post_mcp({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, timeout=10)
                return self._json({"ok": True, "whitelist_prefixes": list(WHITELIST_PREFIXES),
                                    "mcp_tools": mcp_tools.get("result", {}).get("tools", [])})
            except Exception as e:
                return self._json({"ok": False, "error": str(e)}, 500)
        return self._json({"ok": False, "error": "not found"}, 404)

    def do_POST(self):
        if not self._check_auth(): return self._json({"ok": False, "error": "unauthorized"}, 401)
        n = int(self.headers.get("Content-Length", "0") or 0)
        try:
            data = json.loads(self.rfile.read(n).decode() or "{}")
        except Exception as e:
            return self._json({"ok": False, "error": f"bad json: {e}"}, 400)

        if self.path == "/run":
            cmd = (data.get("command") or "").strip()
            if not cmd: return self._json({"ok": False, "error": "missing command"}, 400)
            if not _allowed(cmd):
                return self._json({"ok": False, "error": "command not in whitelist",
                                    "allowed": list(WHITELIST_PREFIXES)}, 403)
            return self._json(_run_shell(cmd, timeout=int(data.get("timeout", 60))))

        if self.path == "/tool":
            name = data.get("name"); args = data.get("arguments") or {}
            if not name: return self._json({"ok": False, "error": "missing tool name"}, 400)
            try:
                resp = _post_mcp({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                   "params": {"name": name, "arguments": args}},
                                  timeout=int(data.get("timeout", 60)))
                return self._json({"ok": "error" not in resp, "response": resp})
            except Exception as e:
                return self._json({"ok": False, "error": str(e)}, 500)

        return self._json({"ok": False, "error": "not found"}, 404)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8769)
    a = ap.parse_args()
    print(f"Arena Web Gateway v{VERSION} on http://{a.host}:{a.port} (auth={bool(TOKEN)})", flush=True)
    srv = ThreadingHTTPServer((a.host, a.port), H)
    try: srv.serve_forever()
    except KeyboardInterrupt: pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
