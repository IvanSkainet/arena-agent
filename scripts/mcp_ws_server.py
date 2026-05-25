#!/usr/bin/env python3
"""Arena MCP WebSocket server v0.1 (pure stdlib).

Реализует RFC 6455 WebSocket handshake + frame parsing БЕЗ сторонних библиотек,
чтобы не тащить лишних зависимостей. Каждое сообщение клиента — JSON-RPC,
передаётся в общий tools registry из mcp_stream_server.

Это альтернативный полнодуплексный транспорт. Streamable HTTP остаётся
основным; WS включается отдельным юнитом, если нужно push-уведомления.

Запуск: python3 ws_server.py --host 127.0.0.1 --port 8768
"""
from __future__ import annotations
import base64, hashlib, json, os, socket, struct, sys, threading

# делаем общие tools доступными
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_stream_server import handle_rpc, TOOLS, VERSION  # type: ignore

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

def _accept_key(key: str) -> str:
    return base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()

def _read_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk: raise ConnectionError("peer closed")
        buf += chunk
    return buf

def _recv_frame(sock: socket.socket) -> tuple[int, bytes]:
    """Возвращает (opcode, payload). 0x1=text, 0x2=binary, 0x8=close, 0x9=ping."""
    hdr = _read_exact(sock, 2)
    b1, b2 = hdr[0], hdr[1]
    opcode = b1 & 0x0F
    masked = bool(b2 & 0x80)
    plen = b2 & 0x7F
    if plen == 126: plen = struct.unpack(">H", _read_exact(sock, 2))[0]
    elif plen == 127: plen = struct.unpack(">Q", _read_exact(sock, 8))[0]
    mask = _read_exact(sock, 4) if masked else b""
    data = _read_exact(sock, plen) if plen else b""
    if masked:
        data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    return opcode, data

def _send_frame(sock: socket.socket, opcode: int, payload: bytes) -> None:
    head = bytes([0x80 | opcode])
    n = len(payload)
    if n < 126:   head += bytes([n])
    elif n < 65536: head += bytes([126]) + struct.pack(">H", n)
    else: head += bytes([127]) + struct.pack(">Q", n)
    sock.sendall(head + payload)

def _send_text(sock, s: str): _send_frame(sock, 0x1, s.encode("utf-8"))

def _http_handshake(sock: socket.socket) -> bool:
    """Парсим HTTP upgrade request. Возвращаем True если успешно."""
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk: return False
        data += chunk
        if len(data) > 16384: return False
    headers = {}
    for line in data.split(b"\r\n")[1:]:
        if not line: break
        if b":" in line:
            k, v = line.split(b":", 1); headers[k.strip().lower()] = v.strip()
    key = headers.get(b"sec-websocket-key", b"").decode()
    if not key: return False
    accept = _accept_key(key)
    resp = ("HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n\r\n")
    sock.sendall(resp.encode())
    return True

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


# --- push extension ---
import threading as _th
import time as _time
import pathlib as _pl

SUBS: dict = {}   # topic -> set of socket objects
SUBS_LOCK = _th.Lock()
NOTIFY_QUEUE = _pl.Path.home() / "arena-agent" / "logs" / "ws_notify.queue"
NOTIFY_QUEUE.parent.mkdir(parents=True, exist_ok=True)
NOTIFY_QUEUE.touch(exist_ok=True)


def _subscribe(sock, topic):
    with SUBS_LOCK:
        SUBS.setdefault(topic, set()).add(sock)


def _unsubscribe_all(sock):
    with SUBS_LOCK:
        for t in list(SUBS.keys()):
            SUBS[t].discard(sock)
            if not SUBS[t]:
                del SUBS[t]


def _broadcast(topic, payload):
    msg = json.dumps({"jsonrpc": "2.0", "method": "notify",
                      "params": {"topic": topic, "data": payload}}, ensure_ascii=False)
    with SUBS_LOCK:
        targets = list(SUBS.get(topic, set()))
    dead = []
    for s in targets:
        try:
            _send_text(s, msg)
        except Exception:
            dead.append(s)
    if dead:
        for s in dead:
            _unsubscribe_all(s)


def _notify_watcher():
    """Фоновый поток: tail-f NOTIFY_QUEUE, каждая строка = JSON {topic, data}."""
    pos = NOTIFY_QUEUE.stat().st_size
    while True:
        try:
            sz = NOTIFY_QUEUE.stat().st_size
            if sz < pos:
                pos = 0
            if sz > pos:
                with open(NOTIFY_QUEUE, "rb") as f:
                    f.seek(pos)
                    chunk = f.read().decode("utf-8", "replace")
                    pos = sz
                for line in chunk.splitlines():
                    line = line.strip()
                    if not line: continue
                    try:
                        msg = json.loads(line)
                        _broadcast(msg.get("topic", "default"), msg.get("data"))
                    except Exception:
                        pass
            _time.sleep(0.5)
        except Exception:
            _time.sleep(2)


# запускаем watcher один раз
_th.Thread(target=_notify_watcher, daemon=True).start()
# --- /push extension ---

def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8768)
    a = p.parse_args()
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((a.host, a.port)); srv.listen(8)
    print(f"Arena MCP WS server v{VERSION} ws://{a.host}:{a.port} (tools={len(TOOLS)})", flush=True)
    try:
        while True:
            client, addr = srv.accept()
            threading.Thread(target=_client_loop, args=(client, addr), daemon=True).start()
    except KeyboardInterrupt: pass
    finally: srv.close()

if __name__ == "__main__": main()
