"""Blocking, process-scoped advisory locks for private append-only journals."""
from __future__ import annotations

import contextlib
import time
from pathlib import Path

from arena.inventory.cache_lease import lease_in_directory
from arena.private_paths import pinned_directory


@contextlib.contextmanager
def journal_lock(path: Path, timeout: float = 30):
    with pinned_directory(path.parent) as parent_fd:
        deadline = time.monotonic() + timeout
        while True:
            with lease_in_directory(path, parent_fd) as acquired:
                if acquired:
                    yield parent_fd
                    return
            if time.monotonic() >= deadline:
                raise TimeoutError("private journal is busy")
            time.sleep(.01)
