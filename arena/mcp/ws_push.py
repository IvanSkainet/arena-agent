"""Push notification extension for standalone MCP WebSocket server."""
from __future__ import annotations

import os

from arena.home import agent_home

# Explicit: these are underscore-prefixed, so `import *` never provided
# them. Until v4.155.0 this module called _send_text/_http_handshake that
# were simply not bound -- the resulting NameError was swallowed by a
# per-subscriber `except Exception`, silently marking every WebSocket
# subscriber dead. Confirmed by execution, not by reading.
from arena.mcp.ws_frames import (  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
    Path,
    _send_text,
    json,
    threading,
    time,
)
from arena.private_paths import pinned_directory
from arena.private_state import private_directory

SUBS: dict = {}
SUBS_LOCK = threading.Lock()
NOTIFY_QUEUE = agent_home() / "logs" / "ws_notify.queue"


def _prepare_notify_queue(path: Path) -> None:
    private_directory(path.parent)
    with pinned_directory(path.parent) as parent_fd:
        if parent_fd is None:
            from arena.windows_privacy import restrict_to_current_user

            restrict_to_current_user(path.parent)
            if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
                raise OSError("refusing a linked notification queue")
        name = path if parent_fd is None else path.name
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0),
                        0o600, dir_fd=parent_fd)
        try:
            if parent_fd is not None:
                os.fchmod(fd, 0o600)
            else:
                restrict_to_current_user(path)
        finally:
            os.close(fd)


_prepare_notify_queue(NOTIFY_QUEUE)

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
