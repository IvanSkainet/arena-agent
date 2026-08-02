"""Push notification extension for standalone MCP WebSocket server."""
from __future__ import annotations

# Explicit: these are underscore-prefixed, so `import *` never provided
# them. Until v4.155.0 this module called _send_text/_http_handshake that
# were simply not bound -- the resulting NameError was swallowed by a
# per-subscriber `except Exception`, silently marking every WebSocket
# subscriber dead. Confirmed by execution, not by reading.
from arena.mcp.ws_frames import Path, _send_text, json, threading, time

SUBS: dict = {}
SUBS_LOCK = threading.Lock()
NOTIFY_QUEUE = Path.home() / "arena-bridge" / "logs" / "ws_notify.queue"
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
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                        _broadcast(msg.get("topic", "default"), msg.get("data"))
                    except Exception:
                        pass
            time.sleep(0.5)
        except Exception:
            time.sleep(2)
