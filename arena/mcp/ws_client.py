"""Client loop for standalone MCP WebSocket server."""
from __future__ import annotations

from arena.mcp.ws_frames import *  # noqa: F401,F403
from arena.mcp.ws_push import _subscribe, _unsubscribe_all

def _client_loop(sock: socket.socket, addr):
    try:
        if not _http_handshake(sock):
            sock.close(); return
        sys.stderr.write(f"WS client connected: {addr}\n")
        while True:
            op, data = _recv_frame(sock)
            if op == 0x8:  # close
                _send_frame(sock, 0x8, b""); break
            if op == 0x9:  # ping
                _send_frame(sock, 0xA, data); continue
            if op == 0xA:  # pong
                continue
            if op in (0x1, 0x2):
                try:
                    msg = json.loads(data.decode("utf-8"))
                    method = msg.get("method", "")
                    if method == "subscribe":
                        topic = (msg.get("params") or {}).get("topic", "default")
                        _subscribe(sock, topic)
                        _send_text(sock, json.dumps({"jsonrpc":"2.0","id":msg.get("id"),
                                                       "result":{"subscribed":topic}}, ensure_ascii=False))
                        continue
                    if method == "unsubscribe":
                        _unsubscribe_all(sock)
                        _send_text(sock, json.dumps({"jsonrpc":"2.0","id":msg.get("id"),
                                                       "result":{"unsubscribed":True}}, ensure_ascii=False))
                        continue
                    resp = handle_rpc(msg)
                    if resp is not None: _send_text(sock, json.dumps(resp, ensure_ascii=False))
                except Exception as e:
                    _send_text(sock, json.dumps({"jsonrpc": "2.0", "error": {"code": -32603, "message": str(e)}}))
    except (ConnectionError, OSError) as e:
        sys.stderr.write(f"WS client {addr} disconnected: {e}\n")
    finally:
        _unsubscribe_all(sock)
        try: sock.close()
        except Exception: pass
