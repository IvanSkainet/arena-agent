"""Standalone pure-stdlib MCP WebSocket server CLI."""
from __future__ import annotations

from arena.mcp.ws_client import _client_loop
from arena.mcp.ws_frames import TOOLS, VERSION, socket, threading
from arena.mcp.ws_push import NOTIFY_QUEUE, _notify_watcher, _prepare_notify_queue


def main() -> None:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8768)
    a = p.parse_args()
    # Before the watcher and before the socket: a queue that cannot be made
    # private stops the server instead of leaving it serving without push.
    _prepare_notify_queue(NOTIFY_QUEUE)
    threading.Thread(target=_notify_watcher, daemon=True).start()
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((a.host, a.port))
    srv.listen(8)
    print(f"Arena MCP WS server v{VERSION} ws://{a.host}:{a.port} (tools={len(TOOLS)})", flush=True)
    try:
        while True:
            client, addr = srv.accept()
            threading.Thread(target=_client_loop, args=(client, addr), daemon=True).start()
    except KeyboardInterrupt:
        pass
    finally:
        srv.close()
