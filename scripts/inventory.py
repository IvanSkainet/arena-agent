#!/usr/bin/env python3
"""Thin CLI wrapper for the modular Arena inventory implementation."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from arena.inventory.cli import main  # noqa: E402
from arena.inventory.probe_common import _run as _common_run, _which as _common_which  # noqa: E402


def _run(*args, **kwargs):
    return _common_run(*args, **kwargs)


def _which(name: str):
    return _common_which(name)


def _ver(cmd_name: str, version_arg: str = "--version", timeout: float = 3.0):
    path = _which(cmd_name)
    if not path:
        return None
    out = _run([path, version_arg], timeout=timeout)
    if not out:
        out = _run([path, version_arg], timeout=timeout, capture_stderr=True)
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    if not lines:
        return path
    noisy = ("could not be loaded", "unrecognized option", "unknown option", "usage:", "try \'")
    for line in lines[:4]:
        if any(x in line.lower() for x in noisy):
            return path
    return lines[0][:200]

if __name__ == "__main__":
    raise SystemExit(main())
