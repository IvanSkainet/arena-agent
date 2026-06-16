"""Standalone MCP HTTP handler."""
from __future__ import annotations

from arena.mcp.standalone_common import *  # noqa: F401,F403
from arena.mcp.standalone_rpc import handle_rpc

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
