"""Standalone MCP Streamable HTTP server components."""
from __future__ import annotations

import json  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import os
import secrets
import shutil  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import sys  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
from typing import Any  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)

from arena.mcp.tool_utils import make_run_local, make_run_sd

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

# Both runners used to be re-implemented here, byte for byte, next to the
# copies in arena/mcp/tool_utils.py. They are now bound to the shared
# factories: one definition, one place to fix, and the `utf8_child` opt-in
# introduced for #127 reaches this dispatcher too.
#
# No subprocess kwargs of their own -- the standalone server has no GUI
# console to hide, which is the only thing the callable feeds the factories.
run_sd = make_run_sd(bin_dir=BIN, subprocess_kwargs=dict)
run_local = make_run_local(dict, bin_dir=BIN)
