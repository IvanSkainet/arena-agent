"""Common helpers for legacy hardware info collection."""
from __future__ import annotations

import platform
import subprocess


def empty_hwinfo() -> dict:
    return {
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "node": platform.node(),
        },
        "motherboard": None,
        "bios": None,
        "cpu": None,
        "gpu": None,
        "gpus": [],
        "ram_total_gb": None,
        "ram_used_gb": None,
        "ram_avail_gb": None,
        "ram_modules": [],
        "disks": [],
    }


def run_text(cmd, *, subprocess_kwargs_fn, timeout: int = 8) -> str:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **subprocess_kwargs_fn())
        return result.stdout if result.returncode == 0 else ""
    except (subprocess.TimeoutExpired, Exception):
        return ""
