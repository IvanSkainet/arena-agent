"""Shared MCP tool execution/response helpers."""
from __future__ import annotations

import os
import platform
import subprocess
from collections.abc import Callable
from typing import Any


def make_run_local(subprocess_kwargs: Callable[[], dict[str, Any]]):
    def run_local(argv: list[str], timeout: int = 30) -> tuple[int, str, str]:
        """Run a command directly (no GUI/sandbox needed)."""
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, **subprocess_kwargs())
        return p.returncode, p.stdout, p.stderr

    return run_local


def make_run_sd(*, bin_dir: Any, subprocess_kwargs: Callable[[], dict[str, Any]]):
    def run_sd(argv: list[str], timeout: int = 60) -> tuple[int, str, str]:
        """Run command via sd-exec (Linux) or directly (Windows)."""
        if platform.system() == "Windows":
            p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, shell=True, **subprocess_kwargs())
            return p.returncode, p.stdout, p.stderr
        sd = os.path.join(bin_dir, "sd-exec")
        p = subprocess.run([sd, "--timeout", str(timeout), "--"] + argv,
                           capture_output=True, text=True, timeout=timeout + 10, **subprocess_kwargs())
        return p.returncode, p.stdout, p.stderr

    return run_sd


def text_content(s: str) -> dict:
    return {"content": [{"type": "text", "text": s}]}
