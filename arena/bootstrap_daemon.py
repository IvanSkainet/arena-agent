"""Unix daemonization bootstrap helper."""
from __future__ import annotations

import os
import sys
from collections.abc import Callable


def daemonize(*, log_error: Callable[..., None] | None = None) -> None:
    """Double-fork to daemonize on Linux."""
    if os.name == "nt":
        return
    try:
        pid = os.fork()
        if pid > 0:
            os._exit(0)
    except OSError as e:
        if log_error:
            log_error("[ArenaBridge] First fork failed: %s", e)
        return

    os.setsid()
    os.umask(0)

    try:
        pid = os.fork()
        if pid > 0:
            os._exit(0)
    except OSError as e:
        if log_error:
            log_error("[ArenaBridge] Second fork failed: %s", e)
        return

    sys.stdout.flush()
    sys.stderr.flush()
    devnull_r = open(os.devnull, "r")
    os.dup2(devnull_r.fileno(), sys.stdin.fileno())
    devnull_r.close()
    devnull_w = open(os.devnull, "w")
    os.dup2(devnull_w.fileno(), sys.stdout.fileno())
    os.dup2(devnull_w.fileno(), sys.stderr.fileno())
    devnull_w.close()
