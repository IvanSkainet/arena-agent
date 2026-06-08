#!/usr/bin/env python3
"""Arena MCP Streamable HTTP server v0.3.

Реализует MCP spec 2025-03-26 на трёх транспортах:
  - POST /mcp        — Streamable HTTP (основной, для современных клиентов)
  - GET  /sse        — Server-Sent Events (старый транспорт, для совместимости)
  - POST /messages   — peer message endpoint для SSE сессий
  - GET  /health     — статус сервера

WebSocket опционально на отдельном порту через `ws_server.py` (см. README).

Tools реализованы как настоящие, не заглушки:
  - ping            — pong
  - echo            — повторить input
  - exec            — выполнить команду (вне bridge cgroup через sd-exec)
  - fs.read         — прочитать файл
  - fs.write        — записать файл
  - fs.list         — листинг директории
  - browser.search  — DuckDuckGo поиск (через py_browser)
  - browser.read    — readability-извлечение
  - browser.shot    — скриншот через chromium+sd-exec
  - mem.set/get     — memory facts
  - sys.status      — статус bridge/services
"""
from __future__ import annotations
import json, os, secrets, shutil, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

VERSION = "0.3.0"
HOME = os.path.expanduser("~")
BIN = os.path.join(HOME, "arena-bridge", "bin")
SESSIONS: dict[str, dict] = {}  # session_id -> {created, queue:list}
SLOCK = threading.Lock()

# ---------- helpers ----------
def now_ms() -> int: return int(time.time() * 1000)
def sid() -> str: return secrets.token_urlsafe(18)
def rpc_result(rid, result): return {"jsonrpc": "2.0", "id": rid, "result": result}
def rpc_error(rid, code, msg): return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": msg}}
def text_content(s: str) -> dict: return {"content": [{"type": "text", "text": s}]}

def run_sd(argv: list[str], timeout: int = 60) -> tuple[int, str, str]:
    import platform
    if platform.system() == "Windows":
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, shell=True)
        return p.returncode, p.stdout, p.stderr
    else:
        sd = os.path.join(BIN, "sd-exec")
        p = subprocess.run([sd, "--timeout", str(timeout), "--"] + argv,
                           capture_output=True, text=True, timeout=timeout + 10)
        return p.returncode, p.stdout, p.stderr

def run_local(argv: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """Запуск напрямую (для агент-тулов которые не требуют GUI/sandbox)."""
    p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr

# ---------- tools registry ----------
TOOLS = [
    {"name": "ping", "description": "Return pong (liveness)",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "echo", "description": "Echo arguments back",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "exec", "description": "Run shell command outside bridge cgroup (via sd-exec)",
     "inputSchema": {"type": "object", "properties": {
         "cmd": {"type": "string", "description": "Команда для bash -c"},
         "timeout": {"type": "integer", "default": 60}}, "required": ["cmd"]}},
    {"name": "fs.read", "description": "Read file contents (utf-8)",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string"}, "max_bytes": {"type": "integer", "default": 200000}},
         "required": ["path"]}},
    {"name": "fs.write", "description": "Write file (utf-8). Создаёт директории.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "fs.list", "description": "List directory entries",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "browser.search", "description": "DuckDuckGo search via pure-Python (no chromium)",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string"}, "n": {"type": "integer", "default": 5}},
         "required": ["query"]}},
    {"name": "browser.read", "description": "Readability-extract clean text from URL",
     "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}},
    {"name": "browser.shot", "description": "Take headless chromium screenshot via sd-exec",
     "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}},
    {"name": "mem.set", "description": "Remember a fact",
     "inputSchema": {"type": "object", "properties": {
         "key": {"type": "string"}, "value": {"type": "string"},
         "tags": {"type": "array", "items": {"type": "string"}}}, "required": ["key", "value"]}},
    {"name": "mem.get", "description": "Recall facts matching query substring",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "sys.status", "description": "Bridge/services/funnel status",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "skill.list", "description": "List available agent skills",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "skill.run",  "description": "Run an agent skill: namespace/name with optional args",
     "inputSchema": {"type": "object", "properties": {
         "name": {"type": "string"},
         "args": {"type": "array", "items": {"type": "string"}, "default": []}},
         "required": ["name"]}},
    {"name": "hooks.list", "description": "List configured hooks per event",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "snapshot",   "description": "Run system snapshot skill and return JSON path",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "subagent.spawn", "description": "Spawn isolated subagent for delegated work; returns summary",
     "inputSchema": {"type": "object", "properties": {
         "cmd": {"type": "string"}, "name": {"type": "string"},
         "wait": {"type": "boolean", "default": True}, "timeout": {"type": "integer", "default": 300}},
         "required": ["cmd"]}},
    {"name": "subagent.list", "description": "List recent subagents",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "memory.recall", "description": "Find relevant facts/snapshots/sessions by query (TF score)",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string"}, "top": {"type": "integer", "default": 5}},
         "required": ["query"]}},
    {"name": "memory.digest", "description": "Compact markdown digest of recent memory (facts/snapshots/subagents)",
     "inputSchema": {"type": "object", "properties": {}}},
]

def call_tool(name: str, args: dict) -> dict:
    """Диспетчер — возвращает MCP content payload."""
    try:
        if name == "ping": return text_content("pong")
        if name == "echo": return text_content(str(args.get("text", "")))
        if name == "exec":
            rc, out, err = run_sd(["bash", "-lc", args["cmd"]], timeout=args.get("timeout", 60))
            return text_content(json.dumps({"exit": rc, "stdout": out[-15000:], "stderr": err[-5000:]}, ensure_ascii=False))
        if name == "fs.read":
            p = os.path.expanduser(args["path"])
            with open(p, "rb") as f: data = f.read(args.get("max_bytes", 200000))
            return text_content(data.decode("utf-8", "replace"))
        if name == "fs.write":
            p = os.path.expanduser(args["path"])
            os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
            with open(p, "w", encoding="utf-8") as f: f.write(args["content"])
            return text_content(f"wrote {len(args['content'])} bytes to {p}")
        if name == "fs.list":
            p = os.path.expanduser(args["path"])
            return text_content(json.dumps(sorted(os.listdir(p))))
        if name == "browser.search":
            rc, out, err = run_local([sys.executable, os.path.join(BIN, "py_browser.py"),
                                       "search", args["query"], "--n", str(args.get("n", 5))], timeout=30)
            return text_content(out or err)
        if name == "browser.read":
            rc, out, err = run_local([sys.executable, os.path.join(BIN, "py_browser.py"),
                                       "read", args["url"]], timeout=30)
            return text_content(out or err)
        if name == "browser.shot":
            import tempfile, platform
            shots = os.path.join(HOME, "arena-bridge", "reports", "shots")
            os.makedirs(shots, exist_ok=True)
            png = os.path.join(shots, f"mcp-{int(time.time())}.png")
            ud = os.path.join(tempfile.gettempdir(), f"cr-mcp-{os.getpid()}")
            chrome_candidates = [
                    "chromium", "chrome", "google-chrome", "google-chrome-stable",
                    "librewolf", "brave", "brave-browser", "firefox", "vivaldi", "yandex-browser", "opera", "tor-browser", "arc", "comet",
                    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                    os.path.join(os.path.expanduser("~"), "AppData", "Local", "Google", "Chrome", "Application", "chrome.exe"),
                    r"C:\Program Files\LibreWolf\librewolf.exe",
                    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
                    r"C:\Program Files\Mozilla Firefox\firefox.exe",
                    r"C:\Program Files\Vivaldi\Application\vivaldi.exe",
                    os.path.join(os.path.expanduser("~"), "AppData", "Local", "Yandex", "YandexBrowser", "Application", "browser.exe"),
                    r"C:\Program Files\Yandex\YandexBrowser\Application\browser.exe",
                    r"C:\Program Files\Opera\launcher.exe",
                    os.path.join(os.path.expanduser("~"), "AppData", "Local", "Programs", "Opera", "launcher.exe"),
                    r"C:\Program Files\Tor Browser\Browser\firefox.exe",
                    os.path.join(os.path.expanduser("~"), "AppData", "Local", "Arc", "Arc.exe"),
                    r"C:\Program Files\Comet\comet.exe",
                    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                    "msedge.exe"
                ]
            if platform.system() == "Windows":
                chrome_candidates = [
                    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                    "msedge.exe",
                    "chrome.exe",
                    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files\Chromium\Application\chrome.exe",
                    r"C:\Program Files\LibreWolf\librewolf.exe",
                ]
            chrome_exe = next((shutil.which(c) or (c if os.path.exists(c) else None) for c in chrome_candidates if shutil.which(c) or os.path.exists(c)), None) or "chrome.exe"
            rc, out, err = run_sd([chrome_exe, "--headless=new", "--no-sandbox", "--disable-gpu",
                                    f"--user-data-dir={ud}", "--window-size=1366,768",
                                    f"--screenshot={png}", args["url"]], timeout=45)
            return text_content(json.dumps({"ok": rc == 0, "screenshot": png, "url": args["url"]}))
        if name == "mem.set":
            tags = args.get("tags") or []
            cmd_args = [os.path.join(BIN, "agentctl"), "mem", "set", args["key"], args["value"]]
            if tags: cmd_args += ["--tags"] + list(tags)
            rc, out, err = run_local(cmd_args, timeout=15)
            return text_content(out or err)
        if name == "mem.get":
            rc, out, err = run_local([os.path.join(BIN, "agentctl"), "mem", "get", args["query"]], timeout=15)
            return text_content(out or err)
        if name == "sys.status":
            rc, out, err = run_local([os.path.join(BIN, "agentctl"), "sys", "status"], timeout=30)
            return text_content(out or err)
        if name == "skill.list":
            rc, out, err = run_local([os.path.join(BIN, "agentctl"), "skill", "list"], timeout=15)
            return text_content(out or err)
        if name == "skill.run":
            sk = args.get("name", "")
            extra = args.get("args") or []
            rc, out, err = run_local([os.path.join(BIN, "agentctl"), "skill", "run", sk] + list(extra), timeout=300)
            return text_content(json.dumps({"exit": rc, "stdout": out[-15000:], "stderr": err[-3000:]}, ensure_ascii=False))
        if name == "hooks.list":
            rc, out, err = run_local([sys.executable, os.path.join(BIN, "hooks_runner.py"), "list"], timeout=10)
            return text_content(out or err)
        if name == "snapshot":
            rc, out, err = run_local([os.path.join(BIN, "agentctl"), "skill", "run", "system/sys-snapshot"], timeout=60)
            return text_content(out or err)
        if name == "subagent.spawn":
            cmd_args = [sys.executable, os.path.join(BIN, "subagent.py"), "spawn", args.get("cmd", "")]
            if args.get("name"): cmd_args += ["--name", args["name"]]
            if args.get("wait", True): cmd_args += ["--wait"]
            cmd_args += ["--timeout", str(args.get("timeout", 300))]
            rc, out, err = run_local(cmd_args, timeout=args.get("timeout", 300) + 30)
            return text_content(out or err)
        if name == "subagent.list":
            rc, out, err = run_local([sys.executable, os.path.join(BIN, "subagent.py"), "list"], timeout=10)
            return text_content(out or err)
        if name == "memory.recall":
            cmd_args = [sys.executable, os.path.join(BIN, "memory_recall.py"), "recall", args.get("query", ""),
                        "--top", str(args.get("top", 5))]
            rc, out, err = run_local(cmd_args, timeout=15)
            return text_content(out or err)
        if name == "memory.digest":
            rc, out, err = run_local([sys.executable, os.path.join(BIN, "memory_recall.py"), "digest"], timeout=15)
            return text_content(out or err)
    except Exception as e:
        return {"isError": True, "content": [{"type": "text", "text": f"ERROR: {type(e).__name__}: {e}"}]}
    return {"isError": True, "content": [{"type": "text", "text": f"Unknown tool: {name}"}]}

# ---------- JSON-RPC ----------
def handle_rpc(msg: dict) -> dict | None:
    m = msg.get("method", ""); rid = msg.get("id")
    if m == "initialize":
        return rpc_result(rid, {"protocolVersion": "2025-03-26",
                                 "serverInfo": {"name": "arena-local-mcp-stream", "version": VERSION},
                                 "capabilities": {"tools": {"listChanged": False}}})
    if m == "tools/list":
        return rpc_result(rid, {"tools": TOOLS})
    if m == "tools/call":
        params = msg.get("params") or {}
        return rpc_result(rid, call_tool(params.get("name", ""), params.get("arguments") or {}))
    if m == "notifications/initialized":
        return None
    return rpc_error(rid, -32601, f"Method not found: {m}")

# ---------- HTTP handler ----------
ALLOWED_ORIGINS = {"http://localhost", "http://127.0.0.1", os.getenv("ARENA_BRIDGE_URL", ""), "null", ""}

class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a): sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), fmt % a))

    def _origin_ok(self):
        o = self.headers.get("Origin", "")
        if not o: return True
        for base in ALLOWED_ORIGINS:
            if o == base or o.startswith(base + ":") or o.startswith(base):
                return True
        return False

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "*"))
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Mcp-Session-Id, Last-Event-ID, Authorization")
        self.send_header("Access-Control-Expose-Headers", "Mcp-Session-Id")

    def _json(self, obj, code=200, extra=None):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code); self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items(): self.send_header(k, v)
        self.end_headers(); self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            with SLOCK: nsess = len(SESSIONS)
            return self._json({"ok": True, "service": "arena-mcp-stream", "version": VERSION,
                               "sessions": nsess, "endpoint": "/mcp", "tools": len(TOOLS)})
        if self.path.startswith("/sse"):
            # SSE legacy: открыть стрим
            session = sid()
            with SLOCK: SESSIONS[session] = {"created": now_ms(), "queue": []}
            self.send_response(200); self._cors()
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                self.wfile.write(f"event: endpoint\ndata: /messages?session_id={session}\n\n".encode())
                self.wfile.flush()
                # держим открытым до DELETE/close
                while True:
                    time.sleep(15)
                    self.wfile.write(b": keepalive\n\n"); self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError): pass
            with SLOCK: SESSIONS.pop(session, None)
            return
        self.send_response(404); self.end_headers()

    def do_POST(self):
        if not self._origin_ok():
            return self._json({"error": "origin not allowed"}, 403)
        n = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(n) if n else b""
        try: msg = json.loads(body.decode("utf-8"))
        except Exception: return self._json(rpc_error(None, -32700, "Parse error"), 400)

        if self.path.startswith("/mcp"):
            # Streamable HTTP — основной endpoint
            session_hdr = self.headers.get("Mcp-Session-Id", "")
            if msg.get("method") == "initialize":
                session = sid()
                with SLOCK: SESSIONS[session] = {"created": now_ms(), "queue": []}
                resp = handle_rpc(msg)
                return self._json(resp, extra={"Mcp-Session-Id": session})
            resp = handle_rpc(msg)
            if resp is None: return self._json({}, 204)
            return self._json(resp)

        if self.path.startswith("/messages"):
            # SSE legacy peer endpoint
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            session = (q.get("session_id") or [""])[0]
            resp = handle_rpc(msg)
            # для legacy SSE мы должны просто принять; ответ дойдёт через SSE стрим (упрощённо: возвращаем сразу)
            self.send_response(202); self._cors(); self.end_headers()
            return

        self.send_response(404); self.end_headers()

    def do_DELETE(self):
        if self.path.startswith("/mcp"):
            sess = self.headers.get("Mcp-Session-Id", "")
            with SLOCK: SESSIONS.pop(sess, None)
            self.send_response(204); self._cors(); self.end_headers(); return
        self.send_response(404); self.end_headers()

def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8767)
    a = p.parse_args()
    print(f"Arena MCP Stream server v{VERSION} on http://{a.host}:{a.port}/mcp", flush=True)
    srv = ThreadingHTTPServer((a.host, a.port), H)
    try: srv.serve_forever()
    except KeyboardInterrupt: pass

if __name__ == "__main__": main()
