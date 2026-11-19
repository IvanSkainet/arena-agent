"""One serialized append protocol shared by every facts-journal writer."""
from __future__ import annotations

import json
import os
from pathlib import Path

from arena.file_lock import journal_lock
from arena.private_state import private_directory


def append_fact_record(path: Path, record: dict) -> None:
    private_directory(path.parent)
    encoded = (json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    with journal_lock(path.with_name(path.name + ".append-lock")):
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "a+b") as stream:
            if os.name != "nt":
                os.fchmod(stream.fileno(), 0o600)
            stream.seek(0, 2)
            separator = b""
            if stream.tell():
                stream.seek(-1, 2)
                if stream.read(1) != b"\n":
                    separator = b"\n"
            stream.write(separator + encoded)
