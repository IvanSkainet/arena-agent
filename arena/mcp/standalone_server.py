"""Standalone MCP Streamable HTTP server CLI."""
from __future__ import annotations

import argparse

from arena.mcp.standalone_common import ThreadingHTTPServer, VERSION
from arena.mcp.standalone_http import H


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8767)
    a = p.parse_args()
    print(f"Arena MCP Stream server v{VERSION} on http://{a.host}:{a.port}/mcp", flush=True)
    srv = ThreadingHTTPServer((a.host, a.port), H)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
