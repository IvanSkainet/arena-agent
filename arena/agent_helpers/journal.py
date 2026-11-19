"""One serialized append protocol shared by every facts-journal writer."""
from __future__ import annotations

import contextlib
import json
import os
import stat
from pathlib import Path

from arena.file_lock import journal_lock
from arena.private_paths import is_linked_path
from arena.private_state import private_directory


def append_fact_record(path: Path, record: dict) -> None:
    private_directory(path.parent)
    encoded = (json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    with journal_lock(path.with_name(path.name + ".append-lock")) as parent_fd:
        with _open_journal(path, parent_fd) as stream:
            _append_complete_record(stream, encoded)


@contextlib.contextmanager
def _open_journal(path: Path, parent_fd: int | None):
    if parent_fd is None and is_linked_path(path):
        raise OSError("refusing a linked fact journal")
    name = path if parent_fd is None else path.name
    flags = os.O_CREAT | os.O_RDWR | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(name, flags, 0o600, dir_fd=parent_fd)
    with os.fdopen(fd, "a+b") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise OSError("fact journal must be a regular file")
        if os.name != "nt":
            os.fchmod(stream.fileno(), 0o600)
        yield stream


def _append_complete_record(stream, encoded: bytes) -> None:
    stream.seek(0, 2)
    separator = b""
    if stream.tell():
        stream.seek(-1, 2)
        if stream.read(1) != b"\n":
            separator = b"\n"
    stream.write(separator + encoded)
