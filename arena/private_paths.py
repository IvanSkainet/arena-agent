"""Create private missing parents and pin POSIX directory components without links.

Existing shared parents are validated, never chmodded. Keep the descriptor open
through the file operation: checking a pathname and closing it is not a lease.
Windows lacks Python dir_fd operations; deployment ACLs remain authoritative.
"""
from __future__ import annotations

import contextlib
import os
import secrets
import tempfile
from collections.abc import Iterator
from pathlib import Path


def _child_directory(parent_fd: int, name: str, flags: int) -> int:
    try:
        return os.open(name, flags, dir_fd=parent_fd)
    except FileNotFoundError:
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
        return os.open(name, flags, dir_fd=parent_fd)


def _windows_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        try:
            current.mkdir(mode=0o700)
        except FileExistsError:
            pass
        if current.is_symlink() or getattr(current, "is_junction", lambda: False)():
            raise OSError("refusing a linked private parent")
        if not current.is_dir():
            raise NotADirectoryError(str(current))


@contextlib.contextmanager
def pinned_directory(path: Path) -> Iterator[int | None]:
    absolute = Path(os.path.abspath(path))
    if os.name == "nt":
        _windows_components(absolute)
        yield None
        return
    # O_PATH/O_SEARCH needs only search permission, retaining legitimate 0300
    # state directories without granting owner read access for known files.
    access = getattr(os, "O_PATH", getattr(os, "O_SEARCH", os.O_RDONLY))
    flags = access | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(absolute.anchor, flags)
    try:
        for part in absolute.parts[1:]:
            child = _child_directory(fd, part, flags)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def create_staged_file(target: Path, parent_fd: int | None) -> tuple[int, Path]:
    if parent_fd is None:
        fd, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        return fd, Path(name)
    name = f".{target.name}.{secrets.token_hex(16)}.tmp"
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600, dir_fd=parent_fd)
    return fd, target.parent / name


def unlink_staged(path: Path, parent_fd: int | None) -> None:
    if parent_fd is None:
        path.unlink()
    else:
        os.unlink(path.name, dir_fd=parent_fd)


def directory_matches(path: Path, parent_fd: int | None) -> bool:
    if parent_fd is None:
        return True
    try:
        current = os.stat(path, follow_symlinks=False)
    except OSError:
        return False
    pinned = os.fstat(parent_fd)
    return (current.st_dev, current.st_ino) == (pinned.st_dev, pinned.st_ino)
