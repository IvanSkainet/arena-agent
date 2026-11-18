"""Process-lifetime advisory leases for private inventory cache files."""
from __future__ import annotations

import contextlib
import errno
import os
from collections.abc import Iterator
from pathlib import Path

from arena.private_state import private_directory


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
    private_directory(path.parent)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
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
        try:
            if held:
                _unlock(fd)
        finally:
            os.close(fd)
