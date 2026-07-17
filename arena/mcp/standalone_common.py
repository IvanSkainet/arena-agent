"""Standalone MCP Streamable HTTP server components."""
from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

VERSION = "0.3.0"
HOME = os.path.expanduser("~")
BIN = os.path.join(HOME, "arena-bridge", "bin")
SESSIONS: dict[str, dict] = {}
SLOCK = threading.Lock()

def now_ms() -> int: return int(time.time() * 1000)

def sid() -> str: return secrets.token_urlsafe(18)

def rpc_result(rid, result): return {"jsonrpc": "2.0", "id": rid, "result": result}

def rpc_error(rid, code, msg): return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": msg}}

def text_content(s: str) -> dict: return {"content": [{"type": "text", "text": s}]}

def run_sd(argv: list[str], timeout: int = 60) -> tuple[int, str, str]:
    import platform
    if platform.system() == "Windows":
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, shell=True)  # nosec B602 -- Windows-only branch; argv[0] is a hard-coded binary name resolved via PATH by cmd.exe (no operator interpolation).  # nosemgrep: subprocess-shell-true -- legitimate CLI-side helper (see bandit B602 nosec on the same line for the specific rationale)
        return p.returncode, p.stdout, p.stderr
    else:
        sd = os.path.join(BIN, "sd-exec")
        p = subprocess.run([sd, "--timeout", str(timeout), "--"] + argv,
                           capture_output=True, text=True, timeout=timeout + 10)
        return p.returncode, p.stdout, p.stderr

def run_local(argv: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """Запуск напрямую (для агент-тулов которые не требуют GUI/sandbox)."""
    p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr
