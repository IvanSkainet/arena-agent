#!/usr/bin/env python3
"""chat-append helper: append a message to the current chat session JSONL.

Usage: chat_append.py <role> <content>
  role: agent | user | system | tool
"""
from __future__ import annotations
import datetime as dt
import fcntl
import json
import os
import pathlib
import sys


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: chat_append.py <role> <content>", file=sys.stderr)
        return 2
    role, content = sys.argv[1], sys.argv[2]
    root = pathlib.Path(os.environ.get("ARENA_AGENT_HOME",
                                       str(pathlib.Path.home() / "arena-agent")))
    cur = root / "memory" / "sessions" / "current"
    if not cur.exists():
        print("no current session", file=sys.stderr)
        return 3
    target = cur.resolve()
    rec = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "role": role,
        "kind": "message",
        "content": content,
    }
    line = json.dumps(rec, ensure_ascii=False) + "\n"
    with open(target, "a", encoding="utf-8") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            f.write(line)
            f.flush()
        finally:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
    try:
        target.chmod(0o600)
    except OSError:
        pass
    print("appended")
    return 0


if __name__ == "__main__":
    sys.exit(main())
