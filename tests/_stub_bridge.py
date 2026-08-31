"""
Shared HTTP stub bridge server for test suites.

Eliminates duplicate in-test HTTP servers across test_agentctl_breaker,
test_agentctl_bridge, and test_url_cache_fallback (#176, #185).
Binds to an ephemeral port (127.0.0.1, 0) once to avoid port reuse races (#175).
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any


class StubBridge:
    """Toy HTTP server pretending to be a bridge.

    Responses can be injected at construction or mutated mid-test via
    ``self.responses``.
    """

    def __init__(
        self,
        responses: dict[tuple[str, str], tuple[int, Any]] | None = None,
        delays: dict[str, float] | None = None,
        health_status: int = 200,
        *,
        agent_config: dict[str, Any] | None = None,
        config_status: int = 200,
    ) -> None:
        self.responses: dict[tuple[str, str], tuple[int, Any]] = dict(responses or {})
        self.delays: dict[str, float] = dict(delays or {})
        self.health_status: int = health_status
        self.agent_config: dict[str, Any] | None = agent_config
        self.config_status: int = config_status
        self.received: list[tuple[str, str, bytes]] = []
        self.server: HTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.port: int = 0

    def start(self) -> StubBridge:
        outer = self

        class _H(BaseHTTPRequestHandler):
            def _write(self, status: int, body: Any) -> None:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                raw_path = self.path
                path = raw_path.split("?")[0]
                outer.received.append(("GET", raw_path, b""))
                if path in outer.delays:
                    time.sleep(outer.delays[path])
                if path == "/health":
                    if outer.health_status == 200:
                        self._write(200, {"ok": True, "service": "stub", "version": "test"})
                    else:
                        self._write(outer.health_status, {"ok": False, "error": "sick"})
                    return
                if path == "/v1/agent/config":
                    if outer.config_status != 200:
                        self._write(outer.config_status, {"ok": False, "error": "sick"})
                        return
                    if outer.agent_config is not None:
                        self._write(200, outer.agent_config)
                        return
                    resp = outer.responses.get(("GET", path))
                    if resp is not None:
                        status, body = resp
                        self._write(status, body)
                        return
                    self._write(200, {})
                    return
                resp = outer.responses.get(("GET", path))
                if resp is not None:
                    status, body = resp
                    self._write(status, body)
                    return
                self._write(404, {"ok": False, "error": "not found"})

            def do_POST(self) -> None:
                raw_path = self.path
                path = raw_path.split("?")[0]
                length = int(self.headers.get("Content-Length") or 0)
                body_in = self.rfile.read(length) if length else b""
                outer.received.append(("POST", raw_path, body_in))
                if path in outer.delays:
                    time.sleep(outer.delays[path])
                resp = outer.responses.get(("POST", path))
                if resp is not None:
                    status, body = resp
                    self._write(status, body)
                    return
                self._write(404, {"ok": False, "error": "not found"})

            def log_message(self, *_a: Any, **_kw: Any) -> None:
                pass

        # Bind to an ephemeral port so parallel tests don't clash.
        # Bind once and never release: picking a port, closing the socket
        # and rebinding leaves a window in which the kernel may hand the
        # same port to another stub (#175).
        self.server = HTTPServer(("127.0.0.1", 0), _H)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()

    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> StubBridge:
        return self.start()

    def __exit__(self, *args: Any) -> None:
        self.stop()


_StubBridge = StubBridge
