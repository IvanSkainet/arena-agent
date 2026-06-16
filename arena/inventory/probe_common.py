"""Shared helpers for cross-platform inventory probes."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

def _run(cmd: list[str] | str, timeout: float = 5.0, capture_stderr: bool = False, shell: bool = False) -> str:
    """Run a command, return stdout (str) or empty string on failure.

    ``cmd`` is normally a list.  ``shell=True`` is supported only for legacy
    call sites and keeps Windows console windows hidden.  Stderr is appended
    only when explicitly requested, because many version probes print helpful
    diagnostics to stderr even on success.
    """
    try:
        kwargs: dict = {
            "capture_output": True,
            "text": True,
            "timeout": timeout,
            "shell": shell,
            "encoding": "utf-8",
            "errors": "replace",
        }
        if platform.system() == "Windows":
            # Hide console window
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        r = subprocess.run(cmd, **kwargs)
        out = r.stdout or ""
        if capture_stderr and r.stderr:
            out += r.stderr
        return out
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError, ValueError):
        return ""

def _which(name: str) -> Optional[str]:
    return shutil.which(name)

def _ver(cmd_name: str, version_arg: str = "--version", timeout: float = 3.0) -> Optional[str]:
    """Get a compact, low-noise version string if the command exists."""
    path = _which(cmd_name)
    if not path:
        return None
    out = _run([path, version_arg], timeout=timeout)
    if not out:
        # Some tools (e.g. java) only respond to -version on stderr.
        out = _run([path, version_arg], timeout=timeout, capture_stderr=True)
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    if not lines:
        return path
    # Avoid surfacing multi-line CLI error banners as a "version".
    noisy = ("could not be loaded", "unrecognized option", "unknown option", "usage:", "try '")
    for line in lines[:4]:
        low = line.lower()
        if any(x in low for x in noisy):
            continue
        return line
    return path

def _powershell_utf8_command(script: str) -> list[str]:
    """Build a PowerShell command that reliably emits UTF-8 JSON/text.

    Windows PowerShell 5 on localized systems otherwise often writes OEM/ANSI
    bytes, which become mojibake when captured as UTF-8 by Python.
    """
    prefix = (
        "$OutputEncoding = [Console]::OutputEncoding = "
        "[System.Text.UTF8Encoding]::new($false); "
        "[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false); "
    )
    return ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", prefix + script]

def _cim_dt(value: Any) -> str:
    """Normalize CIM/PowerShell date values into readable ISO-ish strings."""
    if value in (None, ""):
        return ""
    if isinstance(value, dict):
        for k in ("DateTime", "value", "Value"):
            if value.get(k):
                return _cim_dt(value[k])
    text = str(value).strip()
    # PowerShell JSON for DateTime may be /Date(1712345678000)/
    m = re.search(r"/Date\((\d+)(?:[+-]\d+)?\)/", text)
    if m:
        try:
            return datetime.fromtimestamp(int(m.group(1)) / 1000, tz=timezone.utc).isoformat()
        except Exception:
            return text
    # DMTF CIM datetime: 20260610123456.000000+300
    m = re.match(r"^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})", text)
    if m:
        y, mo, d, h, mi, sec = m.groups()
        return f"{y}-{mo}-{d} {h}:{mi}:{sec}"
    return text

def _get_cim_json(class_name: str, properties: str) -> list[dict]:
    """Parse Get-CimInstance output as JSON (Windows, locale-independent)."""
    try:
        ps = (
            f"Get-CimInstance {class_name} -ErrorAction SilentlyContinue | "
            f"Select-Object {properties} | ConvertTo-Json -Compress -Depth 4"
        )
        out = _run(_powershell_utf8_command(ps), timeout=12)
        if not out or not out.strip():
            return []
        data = json.loads(out.strip())
        if isinstance(data, dict):
            return [data]
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []

__all__ = [name for name in globals() if not name.startswith("__")]
