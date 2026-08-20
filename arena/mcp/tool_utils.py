"""Shared MCP tool execution/response helpers."""
from __future__ import annotations

import os
import platform
import subprocess
from collections.abc import Callable
from typing import Any


def utf8_child_env() -> dict[str, str]:
    """Environment forcing a Python child to speak UTF-8 on stdio.

    Without this a child inherits the console codepage on Windows, so any
    non-Latin-1 character in its output (an emoji in a search snippet, say)
    raises UnicodeEncodeError there and the caller receives nothing. See #127.
    """
    return {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}


def make_run_local(subprocess_kwargs: Callable[[], dict[str, Any]]):
    def run_local(argv: list[str], timeout: int = 30) -> tuple[int, str, str]:
        """Run a command directly (no GUI/sandbox needed)."""
        # Decode as UTF-8 rather than the platform default, and tell the child
        # to encode that way, so the two ends agree no matter the codepage.
        # errors="replace" keeps a stray undecodable byte from destroying an
        # otherwise usable payload.
        kwargs = {"env": utf8_child_env(), **subprocess_kwargs()}
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace", **kwargs)
        return p.returncode, p.stdout, p.stderr

    return run_local


def make_run_sd(*, bin_dir: Any, subprocess_kwargs: Callable[[], dict[str, Any]]):
    def run_sd(argv: list[str], timeout: int = 60) -> tuple[int, str, str]:
        """Run command via sd-exec (Linux) or directly (Windows)."""
        if platform.system() == "Windows":
            p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, shell=True, **subprocess_kwargs())  # nosec B602 -- Windows-only branch; argv[0] is a fixed sd-exec binary path (no operator interpolation).  # nosemgrep: subprocess-shell-true -- legitimate CLI-side helper (see bandit B602 nosec on the same line for the specific rationale)
            return p.returncode, p.stdout, p.stderr
        sd = os.path.join(bin_dir, "sd-exec")
        p = subprocess.run([sd, "--timeout", str(timeout), "--"] + argv,
                           capture_output=True, text=True, timeout=timeout + 10, **subprocess_kwargs())
        return p.returncode, p.stdout, p.stderr

    return run_sd


def text_content(s: str) -> dict:
    return {"content": [{"type": "text", "text": s}]}
