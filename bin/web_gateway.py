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

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(os.environ.get("ARENA_AGENT_HOME", str(Path.home() / "arena-bridge"))).expanduser()
TOKEN = os.environ.get("ARENA_BRIDGE_TOKEN", "")
TOKEN_FILE = Path.home() / "arena-bridge" / "token.txt"
if not TOKEN and TOKEN_FILE.exists():
    TOKEN = TOKEN_FILE.read_text().strip()

# v4.169.33: refuse shells-out through the allow-covering prefix check by
# sharing the same metacharacter set the bridge's exec policy uses. The
# repo root goes on sys.path because this script is run standalone.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from arena.security_commands import SHELL_CONTROL_CHARS  # noqa: E402

MCP_URL = "http://127.0.0.1:8767/mcp"
WHITELIST_PREFIXES = (
    "agentctl skill ", "agentctl mem ", "agentctl recall ",
    "agentctl sub list", "agentctl sub show", "agentctl sub spawn",
    "agentctl browser py-", "agentctl agents ", "agentctl mission list",
    "agentctl sys status", "agentctl hooks list", "agentctl report ",
)

VERSION = "0.1.0"


def _post_mcp(payload: dict, timeout: int = 60) -> dict:
    # The MCP endpoint requires the same bearer token (v4.169.33: it was
    # never forwarded, so every /tool and /tools call came back 401 --
    # nobody noticed because nothing tested the proxy hop).
    req = urllib.request.Request(MCP_URL, data=json.dumps(payload).encode(),
                                  headers={"Content-Type": "application/json",
                                           "Authorization": f"Bearer {TOKEN}"}, method="POST")
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


def _disallowed_reason(cmd: str) -> str | None:
    """Why a /run command must be refused; None when it may run.

    startswith() alone made the whitelist decorative: "agentctl skill list;
    curl attacker" starts with a whitelisted prefix and shell=True then runs
    the rest. A prefix-whitelisted command must be ONE shell command.
    """
    if not any(cmd.startswith(p) for p in WHITELIST_PREFIXES):
        return "command not in whitelist"
    if any(c in cmd for c in SHELL_CONTROL_CHARS):
        return "shell control characters are not allowed with a command whitelist"
    return None


class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        sys.stderr.write(f"{self.address_string()} - - [{self.log_date_time_string()}] {fmt % a}\n")

    def _auth_configured(self) -> bool:
        return bool(TOKEN)

    def _check_auth(self) -> bool:
        # v4.169.33: fail CLOSED. The previous "no token => open (dev mode)"
        # turned a missing config file into an unauthenticated shell endpoint
        # on loopback -- exactly the pattern that was fixed in the input
        # helper. With no token there is nothing to verify a caller against,
        # so privileged endpoints must not serve at all.
        if not TOKEN:
            return False
        h = self.headers.get("X-Arena-Token") or self.headers.get("Authorization", "").replace("Bearer ", "")
        return h == TOKEN

    #: Cap on how much unread request body a response will drain.
    #:
    #: Draining is politeness toward the client, not an obligation to read
    #: whatever it declares: an attacker announcing Content-Length: 10GB must
    #: not be able to make the gateway sit there reading it. Past this cap the
    #: connection is allowed to reset, which is the correct outcome for a body
    #: that large on a refusal path anyway.
    MAX_DRAIN_BYTES = 1 << 20

    #: Wall-clock cap on draining, in seconds.
    #:
    #: A byte cap alone is not enough: a client that announces a large
    #: Content-Length and then sends nothing leaves the handler blocked in
    #: read() with no bytes to count. Measured -- with only the byte cap, such
    #: a request pinned the handler indefinitely. Refusing a caller must never
    #: cost more than this.
    MAX_DRAIN_SECONDS = 2.0

    def _declared_length(self) -> int:
        try:
            return max(0, int(self.headers.get("Content-Length", "0") or 0))
        except (TypeError, ValueError):
            return 0

    def _read_body(self) -> bytes:
        """Read the declared request body, exactly once."""
        if getattr(self, "_body_consumed", False):
            return b""
        self._body_consumed = True
        n = self._declared_length()
        return self.rfile.read(n) if n else b""

    def _drain_request_body(self) -> None:
        """Consume an unread request body before responding.

        A handler that answers and closes while the client is still sending
        makes the Windows TCP stack emit RST instead of FIN, and the client
        sees `WinError 10053` instead of the 401/503 the server actually
        produced. That is not just test flake: a caller who is refused cannot
        tell "you are not authorized" from "the service died", which defeats
        the point of the fail-closed behaviour this gateway exists for.

        Idempotent, so the success path -- which has already read the body --
        does not read again.
        """
        if getattr(self, "_body_consumed", False):
            return
        self._body_consumed = True
        remaining = min(self._declared_length(), self.MAX_DRAIN_BYTES)
        if remaining <= 0:
            return
        sock = self.connection
        original = sock.gettimeout()
        deadline = time.monotonic() + self.MAX_DRAIN_SECONDS
        try:
            while remaining > 0:
                budget = deadline - time.monotonic()
                if budget <= 0:
                    break
                # Bound the blocking read itself: a client that promises bytes
                # and never sends them must not hold the handler open.
                sock.settimeout(budget)
                chunk = sock.recv(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
        except OSError:
            # Timed out or the client vanished; either way, stop draining and
            # let the response go out.
            pass
        finally:
            try:
                sock.settimeout(original)
            except OSError:
                pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self._drain_request_body()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Arena-Token, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        if self.path == "/":
            return self._json({"ok": True, "service": "arena-web-gateway", "version": VERSION,
                                "endpoints": ["/", "/tools", "/run (POST)", "/tool (POST)"],
                                "mcp_proxy": MCP_URL, "auth_required": bool(TOKEN)})
        if self.path == "/tools":
            if not self._auth_configured():
                return self._json({"ok": False, "error": "gateway misconfigured: no token; refusing privileged access"}, 503)
            if not self._check_auth():
                return self._json({"ok": False, "error": "unauthorized"}, 401)
            try:
                mcp_tools = _post_mcp({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, timeout=10)
                return self._json({"ok": True, "whitelist_prefixes": list(WHITELIST_PREFIXES),
                                    "mcp_tools": mcp_tools.get("result", {}).get("tools", [])})
            except Exception as e:
                return self._json({"ok": False, "error": str(e)}, 500)
        return self._json({"ok": False, "error": "not found"}, 404)

    def do_POST(self):
        if not self._auth_configured():
            return self._json({"ok": False, "error": "gateway misconfigured: no token; refusing privileged access"}, 503)
        if not self._check_auth():
            return self._json({"ok": False, "error": "unauthorized"}, 401)
        try:
            data = json.loads(self._read_body().decode() or "{}")
        except Exception as e:
            return self._json({"ok": False, "error": f"bad json: {e}"}, 400)

        if self.path == "/run":
            cmd = (data.get("command") or "").strip()
            if not cmd:
                return self._json({"ok": False, "error": "missing command"}, 400)
            reason = _disallowed_reason(cmd)
            if reason is not None:
                return self._json({"ok": False, "error": reason,
                                    "allowed": list(WHITELIST_PREFIXES)}, 403)
            return self._json(_run_shell(cmd, timeout=int(data.get("timeout", 60))))

        if self.path == "/tool":
            name = data.get("name")
            args = data.get("arguments") or {}
            if not name:
                return self._json({"ok": False, "error": "missing tool name"}, 400)
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
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
