"""Blocking, process-scoped advisory locks for private append-only journals."""
from __future__ import annotations

import contextlib
import time
from pathlib import Path

from arena.inventory.cache_lease import cache_lease


@contextlib.contextmanager
def journal_lock(path: Path, timeout: float = 30):
    deadline = time.monotonic() + timeout
    while True:
        with cache_lease(path) as acquired:
            if acquired:
                yield
                return
        if time.monotonic() >= deadline:
            raise TimeoutError("private journal is busy")
        time.sleep(.01)
