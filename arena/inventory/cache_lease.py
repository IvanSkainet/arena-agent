"""Process-lifetime advisory leases for private inventory cache files."""
from __future__ import annotations

import contextlib
import errno
import os
import stat
from collections.abc import Iterator
from pathlib import Path

from arena.private_paths import is_linked_path, pinned_directory


def _lock(fd: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(fd: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


@contextlib.contextmanager
def cache_lease(path: Path) -> Iterator[bool]:
    """Never unlink a lease file: all processes must lock the same inode.

    Kernel locks are released on crash. A long valid scan cannot lose its
    ownership merely because a wall-clock TTL elapsed. Failure to open the
    private directory is propagated rather than scanning without single-flight.
    """
    with pinned_directory(path.parent) as parent_fd:
        with lease_in_directory(path, parent_fd) as acquired:
            yield acquired


@contextlib.contextmanager
def lease_in_directory(path: Path, parent_fd: int | None) -> Iterator[bool]:
    """Lock a leaf relative to the directory the caller keeps pinned."""
    if parent_fd is None and is_linked_path(path):
        raise OSError("refusing a linked lease")
    name = path if parent_fd is None else path.name
    flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        # Separate first publication from opening the stable lock inode.
        # Only the winner publishes; losers open the existing inode without
        # O_CREAT. This also avoids concurrent non-exclusive creation on
        # APFS (the hosted multiprocess test exercises that platform).
        fd = os.open(name, flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent_fd)
    except FileExistsError:
        fd = os.open(name, flags, dir_fd=parent_fd)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("lease must be a regular file")
        with _held_lease(fd) as acquired:
            yield acquired
    finally:
        os.close(fd)


@contextlib.contextmanager
def _held_lease(fd: int) -> Iterator[bool]:
    held = False
    try:
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"\0")
        try:
            _lock(fd)
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise
            yield False
            return
        held = True
        yield True
    finally:
        if held:
            _unlock(fd)
