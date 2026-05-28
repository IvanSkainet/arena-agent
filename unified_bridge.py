#!/usr/bin/env python3
"""
Arena Unified Bridge v1.8.1

Single asyncio-based process that multiplexes ALL services on one port (8765):
  - /health          GET   Public health check
  - /                GET   API index with endpoints list
  - /v1/version      GET   Version info
  - /v1/info         GET   Bridge info (auth required)
  - /v1/status       GET   Bridge status (auth required)
  - /v1/sysinfo      GET   Hardware/system info (auth required)
  - /v1/hwinfo       GET   Extended hardware info: mobo, BIOS, GPU, RAM modules, disks
  - /v1/backups      GET   List existing backups
  - /v1/backup/{name} GET  Download a specific backup zip
  - /v1/inventory    GET   Full system inventory (runtimes, browsers, etc) via inventory.py
  - /v1/ps           GET   Active processes (auth required)
  - /v1/audit        GET   Audit log (auth required)
  - /v1/audit/stats  GET   Audit statistics (auth required)
  - /v1/exec         POST  Execute command (auth required)
  - /v1/kill         POST  Kill a running process (auth required)
  - /v1/upload       POST  Upload file (auth required)
  - /v1/download     GET   Download file (auth required)
  - /v1/memory       GET   List memory facts (auth required)
  - /v1/memory       POST  Set memory fact (auth required)
  - /v1/missions     GET   List missions (auth required)
  - /v1/mission/show GET   Show mission details (auth required)
  - /v1/beep         POST  Play sound notification (auth required)
  - /v1/doctor       GET   Run diagnostics (auth required)
  - /v1/reports      GET   List reports (auth required)
  - /v1/browser/search GET  Search DuckDuckGo (auth required)
  - /v1/browser/read GET   Readability-extract text (auth required)
  - /v1/browser/dump GET   Full page dump with links (auth required)
  - /v1/browser/fetch GET  Raw content fetch (auth required)
  - /v1/browser/head GET   HTTP HEAD request (auth required)
  - /v1/recall       GET   Smart memory recall with TF scoring (auth required)
  - /v1/recall/digest GET  Memory digest (auth required)
  - /v1/tasks        GET   List task queue (auth required)
  - /v1/tasks        POST  Submit task (auth required)
  - /v1/tasks/clean  POST  Clean completed tasks (auth required)
  - /v1/backup       POST  Create backup (auth required)
  - /v1/skills       GET   List skills (auth required)
  - /v1/skills/run   POST  Run a skill (auth required)
  - /v1/hooks        GET   List hooks (auth required)
  - /v1/agents       GET   List agent configs (auth required)
  - /v1/subagents    GET   List subagents (auth required)
  - /v1/subagents/spawn POST Spawn subagent (auth required)
  - /v1/sys/svc      GET   Service status (auth required)
  - /v1/sys/funnel   GET   Tailscale Funnel status (auth required)
  - /v1/token/regenerate POST  Generate new auth token (rewrites token.txt)
  - /v1/tailscale/funnel/{action} POST  start|stop|status
  - /v1/restart      POST  Graceful shutdown (auto-restart via task/systemd)
  - /v1/config       GET   Token-free configuration dump
  - /v1/metrics      GET   Bridge performance metrics
  - /gui             GET   Dashboard HTML
  - /mcp             POST  MCP Streamable HTTP (JSON-RPC)
  - /mcp             DELETE Close MCP session
  - /sse             GET   MCP SSE legacy transport
  - /messages        POST  MCP SSE peer endpoint
  - /ws              WebSocket MCP transport
  - /run             POST  Web Gateway: run whitelisted command
  - /tool            POST  Web Gateway: proxy MCP tool call
  - /gateway         GET   Web Gateway info
  - /gateway/tools   GET   Web Gateway tools list

Security:
  - Binds to 127.0.0.1 by default (--bind to change)
  - Bearer token required for exec/info/status/audit/upload/download/kill
  - All commands logged to <bridge-dir>/audit.jsonl
  - Destructive patterns blocked (same as v0.4)
  - Profile-based allowlist (cautious / owner-shell)

Architecture:
  asyncio event loop + aiohttp.web for HTTP/WebSocket routing.
  Task runner integrated as asyncio background task (watches queue/inbox).
  Zero external dependencies beyond Python stdlib + aiohttp.
"""
from __future__ import annotations

import sys
import os

# --- Windows pythonw.exe stdout/stderr fix ---
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

# --- Windows resource module mock ---
if sys.platform == "win32":
    class MockResource:
        RLIMIT_NOFILE = 0
        def getrlimit(self, *a, **kw): return (1024, 1024)
        def setrlimit(self, *a, **kw): pass
    sys.modules["resource"] = MockResource()
    import resource  # noqa: E402

import argparse
import asyncio
import base64
import collections
import concurrent.futures
import hashlib
import json
import multiprocessing
import platform
import re
import secrets
import shlex
import signal
import socket
import subprocess
import tempfile
import threading
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import aiohttp
from aiohttp import web

import logging
import logging.handlers
import traceback as _traceback

# ============================================================================
# VERSION & CONSTANTS
# ============================================================================
VERSION = "1.9.4"

# CREATE_NO_WINDOW flag (Windows) — prevents flashing console windows when GUI
# triggers a wmic/powershell/tailscale subprocess. No-op on Linux/macOS.
_NO_WINDOW_FLAG = 0x08000000 if sys.platform == "win32" else 0
def _subprocess_kwargs() -> dict:
    """Common kwargs to silence subprocess child windows on Windows."""
    if sys.platform == "win32":
        return {"creationflags": _NO_WINDOW_FLAG}
    return {}


AUDIT_CMD_LIMIT = 4000
BRIDGE_DIR = Path(__file__).resolve().parent
APP_DIR = BRIDGE_DIR
TOKEN_FILE = APP_DIR / "token.txt"
AUDIT = APP_DIR / "audit.jsonl"
RUN_DIR = APP_DIR / "runs"
MAX_BODY = 1024 * 1024
DEFAULT_MAX_OUTPUT = 2 * 1024 * 1024
DEFAULT_MAX_CONCURRENT = 3

ACTIVE_PROCESSES: dict[str, dict] = {}
audit_lock = threading.Lock()

# ============================================================================
# STRUCTURED LOGGING
# ============================================================================

LOG_FILE = APP_DIR / "bridge.log"


def _setup_logging() -> logging.Logger:
    """Configure structured logging with file rotation and console output."""
    logger = logging.getLogger("arena-bridge")
    logger.setLevel(logging.DEBUG)

    # Prevent duplicate handlers on reload
    if logger.handlers:
        return logger

    # Structured format: timestamp LEVEL [component] message
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console handler (INFO level)
    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # File handler with rotation (DEBUG level, 5MB x 5 files)
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            str(LOG_FILE),
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8"
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:
        # If file logging fails, continue with console only
        pass

    return logger


log = _setup_logging()


# ============================================================================
# CUSTOM EXCEPTIONS (structured error codes for API responses)
# ============================================================================

class BridgeError(Exception):
    """Base exception for all bridge errors. Carries an error_code and HTTP status."""
    error_code: str = "BRIDGE_ERROR"
    http_status: int = 500

    def __init__(self, message: str = "", error_code: str = "", http_status: int = 0):
        super().__init__(message)
        if error_code:
            self.error_code = error_code
        if http_status:
            self.http_status = http_status

    def to_dict(self) -> dict:
        return {
            "ok": False,
            "error": str(self),
            "error_code": self.error_code,
        }


class ValidationError(BridgeError):
    """Input validation failure (400)."""
    error_code = "VALIDATION_ERROR"
    http_status = 400


class AuthError(BridgeError):
    """Authentication failure (401)."""
    error_code = "AUTH_ERROR"
    http_status = 401


class ForbiddenError(BridgeError):
    """Action not allowed (403)."""
    error_code = "FORBIDDEN"
    http_status = 403


class NotFoundError(BridgeError):
    """Resource not found (404)."""
    error_code = "NOT_FOUND"
    http_status = 404


class BridgeTimeoutError(BridgeError):
    """Operation timed out (408)."""
    error_code = "TIMEOUT"
    http_status = 408


class ResourceError(BridgeError):
    """Resource limit exceeded or unavailable (429/503)."""
    error_code = "RESOURCE_ERROR"
    http_status = 503


# ============================================================================
# ERROR MIDDLEWARE (global exception handler)
# ============================================================================

@web.middleware
async def error_middleware(request: web.Request, handler):
    """Catch all unhandled exceptions, return structured JSON, log stack traces."""
    # Generate request ID for tracing
    # Generate or accept request ID (limit client-provided to 64 chars)
    req_id = (request.headers.get("X-Request-Id") or str(uuid.uuid4())[:8])[:64]
    request["req_id"] = req_id

    t0 = time.time()
    try:
        resp = await handler(request)
        duration = time.time() - t0
        log.debug("[%s] %s %s -> %d (%.3fs)", req_id, request.method,
                  request.path, resp.status, duration)
        # Add request ID to response headers
        resp.headers["X-Request-Id"] = req_id
        return resp
    except web.HTTPException as exc:
        duration = time.time() - t0
        log.debug("[%s] %s %s -> HTTPException %d (%.3fs)", req_id, request.method,
                  request.path, exc.status, duration)
        # Add CORS and request ID headers to HTTP exceptions
        exc.headers["Access-Control-Allow-Origin"] = "*"
        exc.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
        exc.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Arena-Token, Mcp-Session-Id"
        exc.headers["X-Request-Id"] = req_id
        raise
    except BridgeError as e:
        duration = time.time() - t0
        _record_request(duration=duration, is_error=True)
        log.warning("[%s] %s %s -> %s %s: %s (%.3fs)", req_id, request.method,
                    request.path, e.error_code, e.http_status, e, duration)
        return _cors_json_response(e.to_dict(), status=e.http_status,
                                   extra_headers={"X-Request-Id": req_id})
    except asyncio.CancelledError:
        raise
    except Exception as e:
        duration = time.time() - t0
        _record_request(duration=duration, is_error=True)
        # Log full stack trace for debugging
        tb = _traceback.format_exc()
        log.error("[%s] %s %s UNHANDLED: %s\n%s", req_id, request.method,
                  request.path, e, tb)
        try:
            audit({"event": "unhandled_error", "req_id": req_id, "path": request.path,
                   "method": request.method, "error": repr(e), "tb_snippet": tb[:2000]})
        except Exception:
            pass  # Don't let audit failure crash the error handler
        return _cors_json_response({
            "ok": False,
            "error": f"Internal error: {type(e).__name__}: {e}",
            "error_code": "INTERNAL_ERROR",
            "req_id": req_id,
        }, status=500, extra_headers={"X-Request-Id": req_id})


# Thread pool executor for running blocking I/O in async handlers
_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="bridge_io")
# Dedicated executor for potentially slow operations (hwinfo, backup)
# to avoid blocking the main executor pool
_SLOW_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="bridge_slow")

# ============================================================================
# CDP (Chrome DevTools Protocol) — Lazy import & session state
# ============================================================================
_cdp_module = None

def _get_cdp_module():
    """Lazily import cdp_browser from scripts/ directory."""
    global _cdp_module
    if _cdp_module is not None:
        return _cdp_module

    # Try multiple locations for cdp_browser.py
    search_paths = [
        BRIDGE_DIR / "scripts",
    ]

    for scripts_dir in search_paths:
        cdp_path = scripts_dir / "cdp_browser.py"
        if cdp_path.exists():
            sys.path.insert(0, str(scripts_dir))
            break

    try:
        import cdp_browser
        _cdp_module = cdp_browser
        return _cdp_module
    except ImportError as e:
        return None


# --- CDP Session State ---
_cdp_state: Dict[str, Any] = {
    "manager": None,           # CDPTabManager instance
    "monitor": None,           # CDPNetworkMonitor instance
    "interceptor": None,       # CDPNetworkInterceptor instance
    "cookie_mgr": None,        # CDPCookieManager instance
    "connected": False,
    "port": 9222,
    "headless": True,
}

_cdp_connecting = False  # Simple flag to prevent concurrent connect/disconnect


# ============================================================================
# BRIDGE METRICS (request counter tracking)
# ============================================================================
BRIDGE_METRICS: dict[str, Any] = {
    "total_requests": 0,
    "total_exec": 0,
    "total_errors": 0,
    "start_time": time.time(),
    "request_durations": [],
}
_metrics_lock = threading.Lock()

CAUTIOUS_ALLOW = {
    "pwd", "ls", "dir", "tree", "find", "fd", "rg", "grep", "cat", "type",
    "head", "tail", "wc", "whoami", "hostname", "uname", "ver", "systeminfo",
    "ipconfig", "ifconfig", "ip", "ss", "netstat", "python", "python3", "py",
    "node", "npm", "pnpm", "yarn", "bun", "deno", "uv", "git", "gh", "go",
    "cargo", "rustc", "java", "javac", "mvn", "gradle", "dotnet", "pacman",
    "paru", "yay", "winget", "choco", "scoop", "pip", "pip3", "bash", "sh",
    "zsh", "fish", "pwsh", "powershell", "cmd", "agentctl",
}

BLOCK_PATTERNS = [
    r"\brm\s+-[^\n]*r[^\n]*f[^\n]*(/|~|\*)",
    r"\bsudo\b",
    r"\bsu\b",
    r"\bmkfs(\.|\s|$)",
    r"\bdd\s+.*\bof\s*=\s*/dev/",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bhalt\b",
    r"\bpoweroff\b",
    r"\bdiskpart\b",
    r"\bformat\s+[A-Za-z]:",
    r"\bbcdedit\b",
    r"\breg\s+delete\b",
    r"\btakeown\b",
    r"\bicacls\b.*\b/grant\b",
    r"\bchmod\s+-R\s+777\s+(/|~)",
    r"(curl|wget).*(\||>)\s*(sh|bash|zsh|fish|pwsh|powershell)",
    r"powershell(\.exe)?\s+.*-(enc|encodedcommand)\b",
]

HOME = str(Path.home())
BIN = str(BRIDGE_DIR / "bin")

# ============================================================================
# HELPERS
# ============================================================================

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_clean_platform_name() -> str:
    p = platform.platform()
    if sys.platform == "win32":
        try:
            build = int(platform.version().split(".")[-1])
            if build >= 22000:
                p = p.replace("Windows-10", f"Windows-11 (Build {build})")
                p = p.replace("Windows-post2016Server", f"Windows-11 (Build {build})")
        except Exception:
            pass
    return p


def decode_output(data: bytes) -> str:
    if os.name == "nt":
        for codec in ["utf-8", "cp866", "cp1251"]:
            try:
                return data.decode(codec, "strict")
            except UnicodeDecodeError:
                continue
    return data.decode("utf-8", "replace")


def read_limited(path: Path, max_bytes: int) -> tuple[str, bool, int]:
    size = path.stat().st_size if path.exists() else 0
    with path.open("rb") as f:
        data = f.read(max_bytes + 1)
    truncated = len(data) > max_bytes or size > max_bytes
    data = data[:max_bytes]
    if os.name == "nt":
        for enc in ["utf-8", "cp866", "cp1251"]:
            try:
                return data.decode(enc), truncated, size
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", "replace"), truncated, size
    try:
        return data.decode("utf-8"), truncated, size
    except Exception:
        return data.decode("utf-8", "replace"), truncated, size


def b64_token(nbytes: int = 32) -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(nbytes)).decode().rstrip("=")


def first_word(cmd: str) -> str:
    try:
        parts = shlex.split(cmd, posix=(os.name != "nt"))
    except Exception:
        parts = cmd.strip().split()
    if not parts:
        return ""
    return Path(parts[0]).name.lower().removesuffix(".exe")


def blocked_reason(cmd: str) -> str | None:
    low = cmd.lower()
    for pat in BLOCK_PATTERNS:
        if re.search(pat, low, flags=re.I | re.S):
            return f"blocked by safety pattern: {pat}"
    return None


def under_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def _record_request(duration: float = 0.0, is_exec: bool = False, is_error: bool = False, count_request: bool = True) -> None:
    """Record a request in the bridge metrics.
    
    count_request=False: Skip incrementing total_requests (used when
    _record_request was already called for this request in the success path).
    """
    with _metrics_lock:
        if count_request:
            BRIDGE_METRICS["total_requests"] += 1
        if is_exec:
            BRIDGE_METRICS["total_exec"] += 1
        if is_error:
            BRIDGE_METRICS["total_errors"] += 1
        if duration > 0:
            BRIDGE_METRICS["request_durations"].append(duration)
            # Keep only last 1000 durations
            if len(BRIDGE_METRICS["request_durations"]) > 1000:
                BRIDGE_METRICS["request_durations"] = BRIDGE_METRICS["request_durations"][-1000:]


def _cors_json_response(data: Any, status: int = 200, extra_headers: dict | None = None, **kwargs: Any) -> web.Response:
    """Return a JSON response with CORS headers. extra_headers merged with CORS."""
    hdrs = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Arena-Token, Mcp-Session-Id",
    }
    if extra_headers:
        hdrs.update(extra_headers)
    return web.json_response(data, status=status, headers=hdrs, **kwargs)


# ============================================================================
# AUDIT
# ============================================================================

def sanitize_audit_event(event: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in event.items():
        lk = k.lower()
        if "token" in lk or "authorization" in lk or "password" in lk or "secret" in lk:
            out[k] = "<redacted>"
            continue
        if k == "cmd" and isinstance(v, str):
            out["cmd_len"] = len(v)
            out["cmd_sha256"] = hashlib.sha256(v.encode("utf-8", "replace")).hexdigest()
            if len(v) > AUDIT_CMD_LIMIT:
                out[k] = v[:AUDIT_CMD_LIMIT] + f"\n...[truncated {len(v) - AUDIT_CMD_LIMIT} chars; sha256={out['cmd_sha256']}]"
                out["cmd_truncated"] = True
            else:
                out[k] = v
                out["cmd_truncated"] = False
            continue
        if isinstance(v, str) and len(v) > 12000:
            out[k] = v[:12000] + f"\n...[truncated {len(v) - 12000} chars]"
            out[k + "_truncated"] = True
        else:
            out[k] = v
    return out


def audit(event: dict[str, Any]) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    event = {"ts": utc_now(), **sanitize_audit_event(event)}
    line = json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
    with audit_lock:
        with AUDIT.open("a", encoding="utf-8") as f:
            f.write(line)
        try:
            os.chmod(AUDIT, 0o600)
        except Exception:
            pass


def read_tail(path: Path, lines: int = 100) -> list[str]:
    if not path.exists():
        return []
    lines = max(1, min(lines, 1000))
    return path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]


# ============================================================================
# MCP TOOLS REGISTRY (from mcp_stream_server.py)
# ============================================================================

MCP_TOOLS = [
    {"name": "ping", "description": "Return pong (liveness)",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "echo", "description": "Echo arguments back",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "exec", "description": "Run shell command outside bridge cgroup (via sd-exec)",
     "inputSchema": {"type": "object", "properties": {
         "cmd": {"type": "string"}, "timeout": {"type": "integer", "default": 60}},
         "required": ["cmd"]}},
    {"name": "fs.read", "description": "Read file contents (utf-8)",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string"}, "max_bytes": {"type": "integer", "default": 200000}},
         "required": ["path"]}},
    {"name": "fs.write", "description": "Write file (utf-8). Creates directories.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "fs.list", "description": "List directory entries",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "browser.search", "description": "DuckDuckGo search via pure-Python (no chromium)",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string"}, "n": {"type": "integer", "default": 5}},
         "required": ["query"]}},
    {"name": "browser.read", "description": "Readability-extract clean text from URL",
     "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}},
    {"name": "browser.shot", "description": "Take headless chromium screenshot via sd-exec",
     "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}},
    {"name": "mem.set", "description": "Remember a fact",
     "inputSchema": {"type": "object", "properties": {
         "key": {"type": "string"}, "value": {"type": "string"},
         "tags": {"type": "array", "items": {"type": "string"}}}, "required": ["key", "value"]}},
    {"name": "mem.get", "description": "Recall facts matching query substring",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "sys.status", "description": "Bridge/services/funnel status",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "skill.list", "description": "List available agent skills",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "skill.run", "description": "Run an agent skill: namespace/name with optional args",
     "inputSchema": {"type": "object", "properties": {
         "name": {"type": "string"}, "args": {"type": "array", "items": {"type": "string"}, "default": []}},
         "required": ["name"]}},
    {"name": "hooks.list", "description": "List configured hooks per event",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "snapshot", "description": "Run system snapshot skill and return JSON path",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "subagent.spawn", "description": "Spawn isolated subagent for delegated work; returns summary",
     "inputSchema": {"type": "object", "properties": {
         "cmd": {"type": "string"}, "name": {"type": "string"},
         "wait": {"type": "boolean", "default": True}, "timeout": {"type": "integer", "default": 300}},
         "required": ["cmd"]}},
    {"name": "subagent.list", "description": "List recent subagents",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "memory.recall", "description": "Find relevant facts/snapshots/sessions by query (TF score)",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string"}, "top": {"type": "integer", "default": 5}},
         "required": ["query"]}},
    {"name": "memory.digest", "description": "Compact markdown digest of recent memory (facts/snapshots/subagents)",
     "inputSchema": {"type": "object", "properties": {}}},
]


def run_local(argv: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """Run a command directly (no GUI/sandbox needed)."""
    p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, **_subprocess_kwargs())
    return p.returncode, p.stdout, p.stderr


def run_sd(argv: list[str], timeout: int = 60) -> tuple[int, str, str]:
    """Run command via sd-exec (Linux) or directly (Windows)."""
    if platform.system() == "Windows":
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, shell=True, **_subprocess_kwargs())
        return p.returncode, p.stdout, p.stderr
    else:
        sd = os.path.join(BIN, "sd-exec")
        p = subprocess.run([sd, "--timeout", str(timeout), "--"] + argv,
                           capture_output=True, text=True, timeout=timeout + 10, **_subprocess_kwargs())
        return p.returncode, p.stdout, p.stderr


def text_content(s: str) -> dict:
    return {"content": [{"type": "text", "text": s}]}


def call_tool(name: str, args: dict) -> dict:
    """MCP tool dispatcher."""
    try:
        if name == "ping":
            return text_content("pong")
        if name == "echo":
            return text_content(str(args.get("text", "")))
        if name == "exec":
            cmd = args.get("cmd", "")
            if not cmd:
                return {"isError": True, "content": [{"type": "text", "text": "ERROR: missing 'cmd' argument"}]}
            if platform.system() == "Windows":
                rc, out, err = run_sd(["cmd", "/c", cmd], timeout=args.get("timeout", 60))
            else:
                rc, out, err = run_sd(["bash", "-lc", cmd], timeout=args.get("timeout", 60))
            return text_content(json.dumps({"exit": rc, "stdout": out[-15000:], "stderr": err[-5000:]}, ensure_ascii=False))
        if name == "fs.read":
            p = os.path.expanduser(args.get("path", ""))
            if not p:
                return {"isError": True, "content": [{"type": "text", "text": "ERROR: missing 'path' argument"}]}
            with open(p, "rb") as f:
                data = f.read(args.get("max_bytes", 200000))
            return text_content(data.decode("utf-8", "replace"))
        if name == "fs.write":
            p = os.path.expanduser(args.get("path", ""))
            content = args.get("content", "")
            if not p:
                return {"isError": True, "content": [{"type": "text", "text": "ERROR: missing 'path' argument"}]}
            os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(content)
            return text_content(f"wrote {len(content)} bytes to {p}")
        if name == "fs.list":
            p = os.path.expanduser(args.get("path", ""))
            if not p:
                return {"isError": True, "content": [{"type": "text", "text": "ERROR: missing 'path' argument"}]}
            return text_content(json.dumps(sorted(os.listdir(p))))
        if name == "browser.search":
            rc, out, err = run_local([sys.executable, os.path.join(BIN, "py_browser.py"),
                                       "search", args.get("query", ""), "--n", str(args.get("n", 5))], timeout=30)
            return text_content(out or err)
        if name == "browser.read":
            rc, out, err = run_local([sys.executable, os.path.join(BIN, "py_browser.py"),
                                       "read", args.get("url", "")], timeout=30)
            return text_content(out or err)
        if name == "browser.shot":
            import shutil as _shutil
            shots = str(REPORTS_DIR / "shots")
            os.makedirs(shots, exist_ok=True)
            png = os.path.join(shots, f"mcp-{int(time.time())}.png")
            ud = os.path.join(tempfile.gettempdir(), f"cr-mcp-{os.getpid()}")
            chrome_candidates = [
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                "msedge.exe", "chrome.exe",
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files\LibreWolf\librewolf.exe",
            ] if platform.system() == "Windows" else [
                "chromium", "chrome", "google-chrome", "google-chrome-stable",
                "librewolf", "brave", "firefox", "vivaldi",
            ]
            chrome_exe = next(
                ((_shutil.which(c) or (c if os.path.exists(c) else None))
                for c in chrome_candidates if _shutil.which(c) or os.path.exists(c)),
                None) or "chrome.exe"
            rc, out, err = run_sd([chrome_exe, "--headless=new", "--no-sandbox", "--disable-gpu",
                                    f"--user-data-dir={ud}", "--window-size=1366,768",
                                    f"--screenshot={png}", args.get("url", "")], timeout=45)
            return text_content(json.dumps({"ok": rc == 0, "screenshot": png, "url": args.get("url", "")}))
        if name == "mem.set":
            tags = args.get("tags") or []
            cmd_args = [os.path.join(BIN, "agentctl"), "mem", "set", args.get("key", ""), args.get("value", "")]
            if tags:
                cmd_args += ["--tags"] + list(tags)
            rc, out, err = run_local(cmd_args, timeout=15)
            return text_content(out or err)
        if name == "mem.get":
            rc, out, err = run_local([os.path.join(BIN, "agentctl"), "mem", "get", args.get("query", "")], timeout=15)
            return text_content(out or err)
        if name == "sys.status":
            rc, out, err = run_local([os.path.join(BIN, "agentctl"), "sys", "status"], timeout=30)
            return text_content(out or err)
        if name == "skill.list":
            rc, out, err = run_local([os.path.join(BIN, "agentctl"), "skill", "list"], timeout=15)
            return text_content(out or err)
        if name == "skill.run":
            sk = args.get("name", "")
            extra = args.get("args") or []
            rc, out, err = run_local([os.path.join(BIN, "agentctl"), "skill", "run", sk] + list(extra), timeout=300)
            return text_content(json.dumps({"exit": rc, "stdout": out[-15000:], "stderr": err[-3000:]}, ensure_ascii=False))
        if name == "hooks.list":
            rc, out, err = run_local([sys.executable, os.path.join(BIN, "hooks_runner.py"), "list"], timeout=10)
            return text_content(out or err)
        if name == "snapshot":
            rc, out, err = run_local([os.path.join(BIN, "agentctl"), "skill", "run", "system/sys-snapshot"], timeout=60)
            return text_content(out or err)
        if name == "subagent.spawn":
            cmd_args = [sys.executable, os.path.join(BIN, "subagent.py"), "spawn", args.get("cmd", "")]
            if args.get("name"):
                cmd_args += ["--name", args["name"]]
            if args.get("wait", True):
                cmd_args += ["--wait"]
            cmd_args += ["--timeout", str(args.get("timeout", 300))]
            rc, out, err = run_local(cmd_args, timeout=args.get("timeout", 300) + 30)
            return text_content(out or err)
        if name == "subagent.list":
            rc, out, err = run_local([sys.executable, os.path.join(BIN, "subagent.py"), "list"], timeout=10)
            return text_content(out or err)
        if name == "memory.recall":
            cmd_args = [sys.executable, os.path.join(BIN, "memory_recall.py"), "recall",
                        args.get("query", ""), "--top", str(args.get("top", 5))]
            rc, out, err = run_local(cmd_args, timeout=15)
            return text_content(out or err)
        if name == "memory.digest":
            rc, out, err = run_local([sys.executable, os.path.join(BIN, "memory_recall.py"), "digest"], timeout=15)
            return text_content(out or err)
    except Exception as e:
        return {"isError": True, "content": [{"type": "text", "text": f"ERROR: {type(e).__name__}: {e}"}]}
    return {"isError": True, "content": [{"type": "text", "text": f"Unknown tool: {name}"}]}


def handle_rpc(msg: dict) -> dict | None:
    """JSON-RPC 2.0 handler for MCP."""
    m = msg.get("method", "")
    rid = msg.get("id")
    if m == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": "2025-03-26",
            "serverInfo": {"name": "arena-unified-bridge", "version": VERSION},
            "capabilities": {"tools": {"listChanged": False}}}}
    if m == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": MCP_TOOLS}}
    if m == "tools/call":
        params = msg.get("params") or {}
        return {"jsonrpc": "2.0", "id": rid, "result": call_tool(params.get("name", ""), params.get("arguments") or {})}
    if m == "notifications/initialized":
        return None
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"Method not found: {m}"}}


# ============================================================================
# MCP SSE SESSIONS
# ============================================================================

MCP_SESSIONS: dict[str, dict] = {}  # session_id -> {created, queue}
MCP_SESSION_MAX_AGE_MS = 3600_000  # 1 hour — stale sessions auto-cleaned


def _cleanup_mcp_sessions() -> int:
    """Remove MCP sessions older than MCP_SESSION_MAX_AGE_MS. Returns count removed."""
    now = now_ms()
    stale = [sid for sid, sess in MCP_SESSIONS.items()
             if now - sess.get("created", 0) > MCP_SESSION_MAX_AGE_MS]
    for sid in stale:
        MCP_SESSIONS.pop(sid, None)
    return len(stale)


def sid() -> str:
    return secrets.token_urlsafe(18)


def now_ms() -> int:
    return int(time.time() * 1000)


# ============================================================================
# WEB GATEWAY WHITELIST
# ============================================================================

GW_WHITELIST = (
    "agentctl skill ", "agentctl mem ", "agentctl recall ",
    "agentctl sub list", "agentctl sub show", "agentctl sub spawn",
    "agentctl browser py-", "agentctl agents ", "agentctl mission list",
    "agentctl sys status", "agentctl hooks list", "agentctl report ",
)


def gw_allowed(cmd: str) -> bool:
    """Check if a gateway command is allowed. Blocks shell metacharacters."""
    if not any(cmd.startswith(p) for p in GW_WHITELIST):
        return False
    for ch in [";", "&", "|", "`", "$", "(", ")", "{", "}", "\n", ">", ">>", "<"]:
        if ch in cmd:
            return False
    return True


# ============================================================================
# TASK RUNNER (integrated asyncio background)
# ============================================================================

ROOT_AGENT = Path(os.environ.get("ARENA_AGENT_HOME", str(BRIDGE_DIR))).expanduser()
QUEUE = ROOT_AGENT / "queue"
INBOX = QUEUE / "inbox"
RUNNING = QUEUE / "running"
DONE = QUEUE / "done"
FAILED = QUEUE / "failed"

# Additional directory constants for new endpoints
SKILLS_DIR = ROOT_AGENT / "skills"
HOOKS_DIR = ROOT_AGENT / "hooks"
AGENTS_DIR = ROOT_AGENT / "agents"
SUBAGENTS_DIR = ROOT_AGENT / "subagents"
MEMORY_FILE = ROOT_AGENT / "memory" / "facts.jsonl"
MISSIONS_DIR = ROOT_AGENT / "missions"
REPORTS_DIR = ROOT_AGENT / "reports"
BACKUPS_DIR = ROOT_AGENT / "backups"


def move_atomic(src: Path, dst: Path) -> None:
    """Atomically move a file, replacing destination if it exists."""
    try:
        if dst.exists():
            dst.unlink()
        src.rename(dst)
    except OSError:
        # Fallback: copy then delete
        import shutil
        shutil.copy2(str(src), str(dst))
        try:
            src.unlink()
        except OSError:
            pass


def task_ensure_dirs():
    for p in [INBOX, RUNNING, DONE, FAILED]:
        p.mkdir(parents=True, exist_ok=True)


async def task_run_one(task_path: Path) -> bool:
    """Process a single task JSON file asynchronously."""
    try:
        task = json.loads(task_path.read_text(encoding="utf-8"))
    except Exception as e:
        log.error("[TaskRunner] Failed to read %s: %s", task_path, e)
        return False

    tid = task.get("id") or task_path.stem
    rp = RUNNING / task_path.name
    try:
        task_path.rename(rp)
    except FileNotFoundError:
        return False

    task["started_at"] = utc_now()
    task["state"] = "running"
    rp.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    cwd = Path(task.get("cwd") or str(Path.home())).expanduser()
    timeout = int(task.get("timeout") or 3600)
    # Apply safety checks (same as /v1/exec)
    blk = blocked_reason(task["cmd"])
    if blk:
        task["state"] = "failed"
        task["exit_code"] = -1
        task["stderr"] = f"blocked: {blk}"
        rp.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        move_atomic(rp, FAILED / rp.name)
        return
    env = os.environ.copy()
    if isinstance(task.get("env"), dict):
        env.update({str(k): str(v) for k, v in task["env"].items()})

    t0 = time.time()
    try:
        proc = await asyncio.create_subprocess_shell(
            task["cmd"], cwd=str(cwd), env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            stdout = stdout.decode("utf-8", "replace")
            stderr = stderr.decode("utf-8", "replace")
            exit_code = proc.returncode
        except asyncio.TimeoutError:
            proc.kill()
            stdout, stderr = "", "timeout"
            exit_code = 124
    except Exception as e:
        stdout, stderr = "", repr(e)
        exit_code = 125

    duration = round(time.time() - t0, 3)
    max_output = int(task.get("max_output") or 2_000_000)
    truncated = False
    if len(stdout.encode("utf-8", "replace")) > max_output:
        stdout = stdout[:max_output]; truncated = True
    if len(stderr.encode("utf-8", "replace")) > max_output:
        stderr = stderr[:max_output]; truncated = True

    state = "done" if exit_code == 0 else "failed"
    task.update({
        "finished_at": utc_now(), "duration_sec": duration,
        "exit_code": exit_code, "stdout": stdout, "stderr": stderr,
        "truncated": truncated, "state": state,
    })
    dest = (DONE if exit_code == 0 else FAILED) / task_path.name
    dest.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        rp.unlink()
    except FileNotFoundError:
        pass

    log.info("[TaskRunner] %s: %s exit=%s dur=%ss", tid, state, exit_code, duration)
    return True


async def task_runner_loop(app: web.Application):
    """Background task: watches INBOX for new tasks every 5 seconds."""
    task_ensure_dirs()
    log.info("[TaskRunner] Watching %s", INBOX)
    while True:
        try:
            task_ensure_dirs()
            for p in sorted(INBOX.glob("*.json"))[:3]:
                await task_run_one(p)
        except Exception as e:
            log.error("[TaskRunner] Loop error: %s", e)
        # Periodic cleanup of stale MCP sessions
        try:
            removed = _cleanup_mcp_sessions()
            if removed:
                log.info("[TaskRunner] Cleaned %d stale MCP sessions", removed)
        except Exception:
            pass
        await asyncio.sleep(5)


# ============================================================================
# APP CONFIG
# ============================================================================

def make_app(cfg: dict) -> web.Application:
    app = web.Application(client_max_size=50 * 1024 * 1024, middlewares=[error_middleware])
    app["cfg"] = cfg
    app["mcp_sessions"] = {}

    # ---- Public endpoints ----
    app.router.add_get("/", handle_index)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/v1/version", handle_v1_version)

    # ---- v1 API (auth required) ----
    app.router.add_get("/v1/info", handle_v1_info)
    app.router.add_get("/v1/status", handle_v1_status)
    app.router.add_get("/v1/sysinfo", handle_v1_sysinfo)
    app.router.add_get("/v1/hwinfo", handle_v1_hwinfo)
    app.router.add_get("/v1/inventory", handle_v1_inventory)
    app.router.add_get("/v1/ps", handle_v1_ps)
    app.router.add_get("/v1/audit", handle_v1_audit)
    app.router.add_post("/v1/exec", handle_v1_exec)
    app.router.add_post("/v1/kill", handle_v1_kill)
    app.router.add_post("/v1/upload", handle_v1_upload)
    app.router.add_get("/v1/download", handle_v1_download)

    # ---- Dashboard API (auth required) ----
    app.router.add_get("/v1/memory", handle_v1_memory)
    app.router.add_post("/v1/memory", handle_v1_memory_set)
    app.router.add_get("/v1/missions", handle_v1_missions)
    app.router.add_post("/v1/beep", handle_v1_beep)
    app.router.add_get("/v1/doctor", handle_v1_doctor)
    app.router.add_get("/v1/reports", handle_v1_reports)
    app.router.add_get("/v1/browser/search", handle_v1_browser_search)
    app.router.add_get("/v1/browser/read", handle_v1_browser_read)

    # ---- v1.5.0 new endpoints ----
    app.router.add_get("/v1/sys/svc", handle_v1_sys_svc)
    app.router.add_get("/v1/service/info", handle_v1_service_info)
    app.router.add_get("/v1/sys/funnel", handle_v1_sys_funnel)
    app.router.add_post("/v1/token/regenerate", handle_v1_token_regenerate)
    app.router.add_post("/v1/tailscale/funnel/{action}", handle_v1_tailscale_funnel)
    app.router.add_get("/v1/tailscale/funnel/{action}", handle_v1_tailscale_funnel)
    app.router.add_post("/v1/restart", handle_v1_restart)
    app.router.add_get("/v1/config", handle_v1_config)
    app.router.add_get("/v1/browser/dump", handle_v1_browser_dump)
    app.router.add_get("/v1/browser/fetch", handle_v1_browser_fetch)
    app.router.add_get("/v1/browser/head", handle_v1_browser_head)

    # ---- CDP (Chrome DevTools Protocol) ----
    app.router.add_get("/v1/browser/cdp/status", handle_v1_cdp_status)
    app.router.add_post("/v1/browser/cdp/connect", handle_v1_cdp_connect)
    app.router.add_post("/v1/browser/cdp/disconnect", handle_v1_cdp_disconnect)
    app.router.add_post("/v1/browser/cdp/navigate", handle_v1_cdp_navigate)
    app.router.add_get("/v1/browser/cdp/screenshot", handle_v1_cdp_screenshot)
    app.router.add_get("/v1/browser/cdp/dom", handle_v1_cdp_dom)
    app.router.add_post("/v1/browser/cdp/eval", handle_v1_cdp_eval)
    app.router.add_post("/v1/browser/cdp/click", handle_v1_cdp_click)
    app.router.add_post("/v1/browser/cdp/type", handle_v1_cdp_type)
    app.router.add_get("/v1/browser/cdp/tabs", handle_v1_cdp_tabs)
    app.router.add_post("/v1/browser/cdp/tabs/new", handle_v1_cdp_tabs_new)
    app.router.add_post("/v1/browser/cdp/tabs/close", handle_v1_cdp_tabs_close)
    app.router.add_post("/v1/browser/cdp/tabs/activate", handle_v1_cdp_tabs_activate)
    app.router.add_get("/v1/browser/cdp/cookies", handle_v1_cdp_cookies_get)
    app.router.add_post("/v1/browser/cdp/cookies", handle_v1_cdp_cookies_set)
    app.router.add_delete("/v1/browser/cdp/cookies", handle_v1_cdp_cookies_delete)
    app.router.add_post("/v1/browser/cdp/cookies/clear", handle_v1_cdp_cookies_clear)
    app.router.add_get("/v1/browser/cdp/cookies/profiles", handle_v1_cdp_cookies_profiles)
    app.router.add_post("/v1/browser/cdp/cookies/profiles", handle_v1_cdp_cookies_profiles)
    app.router.add_post("/v1/browser/cdp/network/start", handle_v1_cdp_network_start)
    app.router.add_post("/v1/browser/cdp/network/stop", handle_v1_cdp_network_stop)
    app.router.add_get("/v1/browser/cdp/network/requests", handle_v1_cdp_network_requests)
    app.router.add_get("/v1/browser/cdp/network/har", handle_v1_cdp_network_har)
    app.router.add_post("/v1/browser/cdp/intercept/start", handle_v1_cdp_intercept_start)
    app.router.add_post("/v1/browser/cdp/intercept/stop", handle_v1_cdp_intercept_stop)
    app.router.add_post("/v1/browser/cdp/intercept/rule", handle_v1_cdp_intercept_rule)
    app.router.add_delete("/v1/browser/cdp/intercept/rule", handle_v1_cdp_intercept_rule)
    app.router.add_get("/v1/browser/cdp/intercept/rules", handle_v1_cdp_intercept_rule)
    app.router.add_get("/v1/browser/cdp/session/check", handle_v1_cdp_session_check)

    app.router.add_get("/v1/recall", handle_v1_recall)
    app.router.add_get("/v1/recall/digest", handle_v1_recall_digest)
    app.router.add_get("/v1/audit/stats", handle_v1_audit_stats)
    app.router.add_get("/v1/tasks", handle_v1_tasks_get)
    app.router.add_post("/v1/tasks", handle_v1_tasks_post)
    app.router.add_post("/v1/tasks/clean", handle_v1_tasks_clean)
    app.router.add_post("/v1/backup", handle_v1_backup)
    app.router.add_get("/v1/backups", handle_v1_backups)
    app.router.add_get("/v1/backup/{name}", handle_v1_backup_download)
    app.router.add_get("/v1/skills", handle_v1_skills)
    app.router.add_post("/v1/skills/run", handle_v1_skills_run)
    app.router.add_get("/v1/hooks", handle_v1_hooks)
    app.router.add_get("/v1/agents", handle_v1_agents)
    app.router.add_get("/v1/subagents", handle_v1_subagents)
    app.router.add_post("/v1/subagents/spawn", handle_v1_subagents_spawn)
    app.router.add_get("/v1/mission/show", handle_v1_mission_show)
    app.router.add_get("/v1/metrics", handle_v1_metrics)
    app.router.add_get("/v1/logs", handle_v1_logs)

    # ---- Dashboard ----
    app.router.add_get("/gui", handle_gui)

    # ---- MCP Streamable HTTP ----
    app.router.add_post("/mcp", handle_mcp_post)
    app.router.add_delete("/mcp", handle_mcp_delete)

    # ---- MCP SSE Legacy ----
    app.router.add_get("/sse", handle_sse)
    app.router.add_post("/messages", handle_sse_messages)

    # ---- MCP WebSocket ----
    app.router.add_get("/ws", handle_ws)

    # ---- Web Gateway ----
    app.router.add_get("/gateway", handle_gateway_index)
    app.router.add_get("/gateway/tools", handle_gateway_tools)
    app.router.add_post("/run", handle_gateway_run)
    app.router.add_post("/tool", handle_gateway_tool)

    # ---- Background tasks ----
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    return app


async def on_startup(app: web.Application):
    """Start background task runner and initialize async primitives."""
    cfg = app["cfg"]
    cfg["semaphore"] = asyncio.Semaphore(cfg["max_concurrent"])
    app["task_runner"] = asyncio.ensure_future(task_runner_loop(app))
    log.info("[UnifiedBridge v%s] Background task runner started", VERSION)


async def on_cleanup(app: web.Application):
    """Stop background task runner."""
    tr = app.get("task_runner")
    if tr:
        tr.cancel()
        try:
            await tr
        except asyncio.CancelledError:
            pass


# ============================================================================
# AUTH HELPER
# ============================================================================

def check_auth(request: web.Request) -> bool:
    cfg = request.app["cfg"]
    token = cfg["token"]
    auth = request.headers.get("Authorization", "")
    if auth == f"Bearer {token}":
        return True
    # Also check X-Arena-Token for gateway compat
    xt = request.headers.get("X-Arena-Token", "")
    if xt == token:
        return True
    return False


def require_auth(request: web.Request) -> web.Response | None:
    """Returns None if auth OK, or a 401 Response if not."""
    if not check_auth(request):
        return _cors_json_response({"ok": False, "error": "unauthorized"}, status=401)
    return None


def common_status(cfg: dict) -> dict:
    return {
        "ok": True,
        "service": "arena-unified-bridge",
        "version": VERSION,
        "host": socket.gethostname(),
        "platform": get_clean_platform_name(),
        "python": sys.version.split()[0],
        "profile": cfg["profile"],
        "root": str(cfg["root"]),
        "auth_required_for_exec": True,
        "active_exec": cfg["active_exec"],
        "max_concurrent": cfg["max_concurrent"],
        "audit": str(AUDIT),
    }


# ============================================================================
# HANDLERS — Public
# ============================================================================

async def handle_index(request: web.Request) -> web.Response:
    try:
        _record_request()
        return _cors_json_response({
            "ok": True,
            "service": "arena-unified-bridge",
            "version": VERSION,
            "endpoints": [
                "/health", "/v1/version", "/v1/info", "/v1/status", "/v1/sysinfo",
                "/v1/ps", "/v1/audit?lines=100", "/v1/audit/stats",
                "POST /v1/exec", "POST /v1/kill",
                "POST /v1/upload?path=", "GET /v1/download?path=",
                "GET /v1/memory?q=", "POST /v1/memory",
                "GET /v1/missions", "GET /v1/mission/show?name=",
                "GET /v1/reports", "GET /v1/doctor", "POST /v1/beep",
                "GET /v1/browser/search?q=", "GET /v1/browser/read?url=",
                "GET /v1/browser/dump?url=", "GET /v1/browser/fetch?url=",
                "GET /v1/browser/head?url=",
                "GET /v1/browser/cdp/status", "POST /v1/browser/cdp/connect", "POST /v1/browser/cdp/disconnect",
                "POST /v1/browser/cdp/navigate", "GET /v1/browser/cdp/screenshot", "GET /v1/browser/cdp/dom",
                "POST /v1/browser/cdp/eval", "POST /v1/browser/cdp/click", "POST /v1/browser/cdp/type",
                "GET /v1/browser/cdp/tabs", "POST /v1/browser/cdp/tabs/new", "POST /v1/browser/cdp/tabs/close",
                "POST /v1/browser/cdp/tabs/activate", "GET/POST/DELETE /v1/browser/cdp/cookies",
                "POST /v1/browser/cdp/cookies/clear", "GET/POST /v1/browser/cdp/cookies/profiles",
                "POST /v1/browser/cdp/network/start", "POST /v1/browser/cdp/network/stop",
                "GET /v1/browser/cdp/network/requests", "GET /v1/browser/cdp/network/har",
                "POST /v1/browser/cdp/intercept/start", "POST /v1/browser/cdp/intercept/stop",
                "POST/DELETE/GET /v1/browser/cdp/intercept/rule|rules",
                "GET /v1/browser/cdp/session/check",

                "GET /v1/recall?q=&top=5", "GET /v1/recall/digest",
                "GET /v1/tasks?status=&limit=20", "POST /v1/tasks", "POST /v1/tasks/clean",
                "POST /v1/backup",
        "GET /v1/backups",
        "GET /v1/backup/{name}",
        "GET /v1/inventory?section=&format=text|json",
                "GET /v1/skills", "POST /v1/skills/run",
                "GET /v1/hooks", "GET /v1/agents",
                "GET /v1/subagents", "POST /v1/subagents/spawn",
                "GET /v1/sys/svc", "GET /v1/sys/funnel",
        "GET /v1/service/info",
        "POST /v1/token/regenerate",
        "POST /v1/tailscale/funnel/{start|stop|status}",
        "POST /v1/restart",
        "GET /v1/config",
                "GET /v1/metrics",
                "/gui", "POST /mcp", "DELETE /mcp",
                "GET /sse", "POST /messages", "GET /ws",
                "/gateway", "/gateway/tools", "POST /run", "POST /tool",
            ],
            "auth_required_for_exec": True,
        })
    except Exception as e:
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_health(request: web.Request) -> web.Response:
    try:
        cfg = request.app["cfg"]
        s = common_status(cfg)
        for k in ["audit", "active_exec", "max_concurrent", "python"]:
            s.pop(k, None)
        # Add uptime_seconds (v1.5.0 improvement)
        s["uptime_seconds"] = round(time.time() - BRIDGE_METRICS["start_time"], 1)
        _record_request()
        return _cors_json_response(s)
    except Exception as e:
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_version(request: web.Request) -> web.Response:
    """GET /v1/version — version info."""
    try:
        _record_request()
        return _cors_json_response({
            "ok": True,
            "version": VERSION,
            "service": "arena-unified-bridge",
            "python": sys.version.split()[0],
            "platform": get_clean_platform_name(),
        })


    # ============================================================================
    # HANDLERS — v1 API
    # ============================================================================
    except Exception as e:
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)

async def handle_v1_info(request: web.Request) -> web.Response:
    try:
        r = require_auth(request)
        if r: return r
        _record_request()
        return _cors_json_response(common_status(request.app["cfg"]))
    except Exception as e:
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_status(request: web.Request) -> web.Response:
    try:
        r = require_auth(request)
        if r: return r
        _record_request()
        return _cors_json_response(common_status(request.app["cfg"]))
    except Exception as e:
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


def _sysinfo_wmic_sync() -> tuple[int, int]:
    """Synchronous helper to run wmic for CPU info (Windows only)."""
    cpu_physical = multiprocessing.cpu_count()
    cpu_logical = multiprocessing.cpu_count()
    try:
        out_bytes = subprocess.check_output(
            "wmic cpu get NumberOfCores,NumberOfLogicalProcessors", shell=True, **_subprocess_kwargs())
        for enc in ["utf-16", "utf-8", "cp866"]:
            try:
                out = out_bytes.decode(enc, errors="ignore")
                break
            except Exception:
                continue
        lines = [l.strip().split() for l in out.splitlines() if l.strip()]
        if len(lines) > 1:
            headers = [h.lower() for h in lines[0]]
            ci = next((i for i, h in enumerate(headers) if "numberofcores" in h), None)
            ti = next((i for i, h in enumerate(headers) if "numberoflogicalprocessors" in h), None)
            if ci is not None and ti is not None:
                cpu_physical = int(lines[1][ci])
                cpu_logical = int(lines[1][ti])
    except Exception:
        pass
    return cpu_physical, cpu_logical


async def handle_v1_sysinfo(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    _record_request()
    cfg = request.app["cfg"]
    try:
        import shutil
        disk = shutil.disk_usage(cfg["root"])
        mem_total, mem_avail = 0, 0

        if sys.platform == "win32":
            try:
                import ctypes
                class MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_uint64), ("ullAvailPhys", ctypes.c_uint64),
                        ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64),
                        ("ullTotalVirtual", ctypes.c_uint64), ("ullAvailVirtual", ctypes.c_uint64),
                        ("ullAvailExtendedVirtual", ctypes.c_uint64),
                    ]
                stat = MEMORYSTATUSEX()
                stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
                ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
                mem_total = stat.ullTotalPhys
                mem_avail = stat.ullAvailPhys
            except Exception:
                pass
        elif os.path.exists("/proc/meminfo"):
            with open("/proc/meminfo") as f:
                m = f.read()
            mt = re.search(r"MemTotal:\s+(\d+)", m)
            ma = re.search(r"MemAvailable:\s+(\d+)", m)
            if mt: mem_total = int(mt.group(1)) * 1024
            if ma: mem_avail = int(ma.group(1)) * 1024

        cpu_physical = multiprocessing.cpu_count()
        cpu_logical = multiprocessing.cpu_count()
        if sys.platform == "win32":
            loop = asyncio.get_event_loop()
            cpu_physical, cpu_logical = await loop.run_in_executor(_EXECUTOR, _sysinfo_wmic_sync)

        # CPU load: cross-platform (Windows has no os.getloadavg)
        cpu_percent = 0.0
        load_avg = [0.0, 0.0, 0.0]
        if sys.platform == "win32":
            try:
                import subprocess as _sp2
                r = _sp2.run(["powershell", "-Command",
                    "(Get-WmiObject Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average"],
                    capture_output=True, text=True, timeout=5, **_subprocess_kwargs())
                cpu_percent = float(r.stdout.strip()) if r.stdout.strip() else 0.0
            except Exception:
                pass
        else:
            load_avg = list(getattr(os, "getloadavg", lambda: (0.0, 0.0, 0.0))())
            cpu_percent = load_avg[0] * 100 / max(cpu_logical, 1) if load_avg[0] > 0 else 0.0
        return _cors_json_response({
            "ok": True,
            "cpu_cores": cpu_physical,
            "cpu_threads": cpu_logical,
            "cpu_percent": round(cpu_percent, 1),
            "load_avg": load_avg,
            "mem_total_mb": mem_total // (1024 * 1024),
            "mem_avail_mb": mem_avail // (1024 * 1024),
            "disk_total_gb": disk.total // (1024 ** 3),
            "disk_free_gb": disk.free // (1024 ** 3),
        })
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


def _hwinfo_sync():
    """Collect extended hardware info. Cross-platform."""
    import subprocess, platform
    import re as _re
    info = {
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

    def _run(cmd, timeout=8):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **_subprocess_kwargs())
            return r.stdout if r.returncode == 0 else ""
        except (subprocess.TimeoutExpired, Exception):
            return ""

    if platform.system() == "Windows":
        # Helper: parse wmic /format:list output as list of dicts.
        # wmic on Windows outputs each "Key=Value" line followed by extra blank lines
        # (Python's text mode converts \r\r\n -> \n\n). Block separator is "\n\n+" run of blanks
        # but in practice every entry has blanks too, so simplest: collect all KV pairs into one block,
        # then split into per-entry blocks based on RECORD pattern.
        # However wmic typically returns ONE entry per call for system items (cpu, bios, baseboard)
        # and we already iterate gpus/disks/memorychip separately.
        # Strategy: treat each contiguous group of non-blank lines as a single record's prefix,
        # but use "key seen twice" as the trigger to start a new block.
        def parse_wmic_list(text):
            text = text.replace("\r\r\n", "\n").replace("\r\n", "\n").replace("\r", "")
            blocks = []
            current = {}
            for line in text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip(); v = v.strip()
                # If we already have this key, start a new record
                if k in current:
                    blocks.append(current)
                    current = {}
                current[k] = v
            if current:
                blocks.append(current)
            return blocks

        # Motherboard
        mb_blocks = parse_wmic_list(_run(["wmic", "baseboard", "get", "Manufacturer,Product,Version", "/format:list"]))
        if mb_blocks and mb_blocks[0].get("Manufacturer"):
            d = mb_blocks[0]
            info["motherboard"] = {
                "manufacturer": d.get("Manufacturer", ""),
                "product": d.get("Product", ""),
                "version": d.get("Version", ""),
            }
        # BIOS
        bios_blocks = parse_wmic_list(_run(["wmic", "bios", "get", "SMBIOSBIOSVersion,Manufacturer,ReleaseDate", "/format:list"]))
        if bios_blocks and bios_blocks[0].get("SMBIOSBIOSVersion"):
            d = bios_blocks[0]
            info["bios"] = {
                "version": d.get("SMBIOSBIOSVersion", ""),
                "manufacturer": d.get("Manufacturer", ""),
                "release_date": d.get("ReleaseDate", "")[:8],
            }
        # CPU
        cpu_blocks = parse_wmic_list(_run(["wmic", "cpu", "get", "Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed", "/format:list"]))
        if cpu_blocks and cpu_blocks[0].get("Name"):
            d = cpu_blocks[0]
            try: cores = int(d.get("NumberOfCores", "0"))
            except: cores = 0
            try: threads = int(d.get("NumberOfLogicalProcessors", "0"))
            except: threads = 0
            try: ghz = round(int(d.get("MaxClockSpeed", "0")) / 1000.0, 2)
            except: ghz = 0
            info["cpu"] = {"name": d["Name"], "cores": cores, "threads": threads, "max_ghz": ghz}
        # GPU
        gpu_blocks = parse_wmic_list(_run(["wmic", "path", "win32_VideoController", "get", "Name,AdapterRAM", "/format:list"]))
        for d in gpu_blocks:
            if d.get("Name"):
                try: vram_mb = int(d.get("AdapterRAM", "0")) // (1024 * 1024)
                except: vram_mb = 0
                info["gpus"].append({"name": d["Name"], "vram_mb": vram_mb})
        if info["gpus"]:
            info["gpu"] = info["gpus"][0]
        # RAM modules
        ram_blocks = parse_wmic_list(_run(["wmic", "memorychip", "get", "Capacity,Speed,Manufacturer,PartNumber", "/format:list"]))
        total_bytes = 0
        for d in ram_blocks:
            if d.get("Capacity"):
                try:
                    cap = int(d["Capacity"])
                    total_bytes += cap
                    info["ram_modules"].append({
                        "size_gb": round(cap / (1024 ** 3), 1),
                        "speed_mhz": int(d.get("Speed", "0") or 0),
                        "manufacturer": d.get("Manufacturer", "").strip(),
                        "part_number": d.get("PartNumber", "").strip(),
                    })
                except Exception:
                    pass
        if total_bytes:
            info["ram_total_gb"] = round(total_bytes / (1024 ** 3), 1)
        # Disks
        disk_blocks = parse_wmic_list(_run(["wmic", "logicaldisk", "get", "DeviceID,Size,FreeSpace,FileSystem,VolumeName", "/format:list"]))
        for d in disk_blocks:
            if d.get("DeviceID") and d.get("Size"):
                try:
                    size = int(d["Size"])
                    free = int(d.get("FreeSpace", "0") or 0)
                    info["disks"].append({
                        "device": d["DeviceID"],
                        "volume": d.get("VolumeName", "").strip(),
                        "filesystem": d.get("FileSystem", "").strip(),
                        "total_gb": round(size / (1024 ** 3), 1),
                        "free_gb": round(free / (1024 ** 3), 1),
                        "used_pct": round((size - free) / size * 100, 1) if size else 0,
                    })
                except Exception:
                    pass

    elif platform.system() == "Linux":
        # CPU via /proc/cpuinfo
        try:
            with open("/proc/cpuinfo") as f:
                cpuinfo = f.read()
            mname = _re.search(r"model name\s*:\s*(.+)", cpuinfo)
            ncpus = len(_re.findall(r"^processor\s*:", cpuinfo, _re.M))
            ncores_set = set(_re.findall(r"core id\s*:\s*(\d+)", cpuinfo))
            info["cpu"] = {
                "name": mname.group(1).strip() if mname else "Unknown",
                "cores": len(ncores_set) or ncpus,
                "threads": ncpus,
                "max_ghz": 0,
            }
        except Exception:
            pass
        # RAM via /proc/meminfo
        try:
            with open("/proc/meminfo") as f:
                m = f.read()
            mt = _re.search(r"MemTotal:\s+(\d+)", m)
            ma = _re.search(r"MemAvailable:\s+(\d+)", m)
            if mt:
                total = int(mt.group(1)) * 1024
                avail = int(ma.group(1)) * 1024 if ma else 0
                info["ram_total_gb"] = round(total / (1024 ** 3), 1)
                info["ram_avail_gb"] = round(avail / (1024 ** 3), 1)
                info["ram_used_gb"] = round((total - avail) / (1024 ** 3), 1)
        except Exception:
            pass
        # Motherboard via dmidecode (usually requires root)
        dmi = _run(["dmidecode", "-t", "baseboard"], timeout=5)
        if dmi:
            mfg = _re.search(r"Manufacturer:\s*(.+)", dmi)
            prod = _re.search(r"Product Name:\s*(.+)", dmi)
            if mfg or prod:
                info["motherboard"] = {
                    "manufacturer": (mfg.group(1).strip() if mfg else ""),
                    "product": (prod.group(1).strip() if prod else ""),
                    "version": "",
                }
        # GPU via lspci
        lspci = _run(["lspci"], timeout=5)
        gpu_match = _re.search(r"VGA compatible controller:\s*(.+)", lspci)
        if gpu_match:
            info["gpu"] = {"name": gpu_match.group(1).strip(), "vram_mb": 0}
            info["gpus"].append(info["gpu"])
        # Disks via df
        df = _run(["df", "-B1", "--output=source,target,fstype,size,avail"], timeout=5)
        for line in df.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 5 and parts[0].startswith("/"):
                try:
                    size = int(parts[3])
                    avail = int(parts[4])
                    if size < 1024 ** 3:
                        continue
                    info["disks"].append({
                        "device": parts[0],
                        "volume": parts[1],
                        "filesystem": parts[2],
                        "total_gb": round(size / (1024 ** 3), 1),
                        "free_gb": round(avail / (1024 ** 3), 1),
                        "used_pct": round((size - avail) / size * 100, 1) if size else 0,
                    })
                except Exception:
                    continue

    return info


# --- /v1/inventory GET — Full system inventory via scripts/inventory.py ---

def _inventory_sync(section: str | None = None, fmt: str = "text", timeout: int = 30) -> dict:
    """Run inventory.py and return the result. Cached for 60 seconds."""
    import subprocess as _sp
    import time as _time

    # Locate inventory.py
    candidates = [
        BRIDGE_DIR / "scripts" / "inventory.py",
        ROOT_AGENT / "scripts" / "inventory.py",
    ]
    script = None
    for c in candidates:
        if c.exists():
            script = c
            break
    if not script:
        return {"ok": False, "error": "inventory.py not found in any known location"}

    args = [sys.executable or "python3", str(script)]
    if fmt == "json":
        args.append("--json")
    if section:
        args.extend(["--section", section])

    try:
        _env = os.environ.copy()
        _env["PYTHONIOENCODING"] = "utf-8"
        _env["PYTHONUTF8"] = "1"
        kwargs: dict = {"capture_output": True, "text": True, "timeout": timeout,
                        "encoding": "utf-8", "errors": "replace", "env": _env}
        if platform.system() == "Windows":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        r = _sp.run(args, **kwargs)
        if fmt == "json":
            try:
                parsed = json.loads(r.stdout)
                return {"ok": r.returncode == 0, "inventory": parsed,
                        "exit_code": r.returncode, "stderr": r.stderr[-2000:]}
            except Exception as e:
                return {"ok": False, "error": f"JSON parse failed: {e}",
                        "stdout": r.stdout[-2000:], "stderr": r.stderr[-2000:]}
        return {"ok": r.returncode == 0, "text": r.stdout,
                "exit_code": r.returncode, "stderr": r.stderr[-2000:],
                "script": str(script)}
    except _sp.TimeoutExpired:
        return {"ok": False, "error": f"inventory.py timed out after {timeout}s"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


async def handle_v1_inventory(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    _record_request()
    section = request.query.get("section")
    fmt = (request.query.get("format") or "text").lower()
    if fmt not in ("text", "json"):
        return _cors_json_response({"ok": False, "error": "format must be 'text' or 'json'"}, status=400)
    try:
        timeout = int(request.query.get("timeout", "30"))
        timeout = min(max(5, timeout), 120)
    except Exception:
        timeout = 30
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _inventory_sync, section, fmt, timeout)
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_hwinfo(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    _record_request()
    try:
        loop = asyncio.get_event_loop()
        # Use dedicated slow executor to avoid blocking the main pool
        info = await asyncio.wait_for(
            loop.run_in_executor(_SLOW_EXECUTOR, _hwinfo_sync),
            timeout=30.0
        )
        return _cors_json_response({"ok": True, "hwinfo": info})
    except asyncio.TimeoutError:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "hwinfo collection timed out (30s) — wmic commands may be hung"}, status=504)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)




async def handle_v1_ps(request: web.Request) -> web.Response:
    try:
        r = require_auth(request)
        if r: return r
        _record_request()
        ps_list = []
        for req_id, info in ACTIVE_PROCESSES.items():
            ps_list.append({
                "request_id": req_id,
                "pid": info["pid"],
                "cmd": info["cmd"][:200],
                "uptime_sec": round(time.time() - info["start"], 1),
            })
        return _cors_json_response({"ok": True, "processes": ps_list, "count": len(ps_list)})
    except Exception as e:
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_audit(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    _record_request()
    qs = parse_qs(request.query_string)
    try:
        n = int(qs.get("lines", ["100"])[0])
    except ValueError:
        n = 100
    loop = asyncio.get_event_loop()
    lines = await loop.run_in_executor(_EXECUTOR, read_tail, AUDIT, n)
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except Exception:
            rows.append({"raw": line})
    return _cors_json_response({"ok": True, "lines": len(rows), "audit": str(AUDIT), "events": rows})


async def handle_v1_exec(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    cfg = request.app["cfg"]

    try:
        data = await request.json()
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": f"invalid json: {e}"}, status=400)

    if not isinstance(data, dict):
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "JSON must be object"}, status=400)

    request_id = str(data.get("request_id") or uuid.uuid4())
    cmd = str(data.get("cmd", "")).strip()
    if not cmd:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing cmd", "request_id": request_id}, status=400)

    # Safety checks
    reason = blocked_reason(cmd)
    if reason:
        audit({"type": "exec_blocked", "request_id": request_id, "cmd": cmd, "reason": reason,
                "client": request.remote or "127.0.0.1"})
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": reason, "request_id": request_id}, status=403)

    profile = cfg["profile"]
    fw = first_word(cmd)
    if profile == "cautious" and fw not in CAUTIOUS_ALLOW:
        reason = f"command '{fw}' not in cautious allowlist; use --profile owner-shell"
        audit({"type": "exec_blocked", "request_id": request_id, "cmd": cmd, "reason": reason,
                "client": request.remote or "127.0.0.1"})
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": reason, "request_id": request_id}, status=403)

    root: Path = cfg["root"]
    cwd_raw = str(data.get("cwd") or root)
    cwd = Path(cwd_raw).expanduser()
    if not cwd.is_absolute():
        cwd = root / cwd
    if not cfg["allow_any_cwd"] and not under_root(cwd, root):
        _record_request(is_error=True, count_request=False)
        return _cors_json_response(
            {"ok": False, "error": f"cwd must be under root {root}", "request_id": request_id}, status=403)
    if not cwd.exists() or not cwd.is_dir():
        _record_request(is_error=True, count_request=False)
        return _cors_json_response(
            {"ok": False, "error": f"cwd does not exist: {cwd}", "request_id": request_id}, status=400)

    timeout = min(int(data.get("timeout", cfg["timeout"])), cfg["max_timeout"])
    max_output = min(int(data.get("max_output", DEFAULT_MAX_OUTPUT)), cfg["max_output"])
    env_extra = data.get("env") if isinstance(data.get("env"), dict) else {}
    env = os.environ.copy()
    env.update({str(k): str(v) for k, v in env_extra.items()})

    sem: asyncio.Semaphore = cfg["semaphore"]
    if sem.locked() and cfg["active_exec"] >= cfg["max_concurrent"]:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response(
            {"ok": False, "error": "too many concurrent exec requests", "request_id": request_id}, status=429)

    await sem.acquire()
    cfg["active_exec"] += 1

    audit({"type": "exec_start", "request_id": request_id, "cmd": cmd, "cwd": str(cwd),
            "timeout": timeout, "client": request.remote or "127.0.0.1"})

    t0 = time.time()
    timed_out = False
    proc = None

    try:
        # Use async subprocess
        proc = await asyncio.create_subprocess_shell(
            cmd, cwd=str(cwd), env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)

        ACTIVE_PROCESSES[request_id] = {"cmd": cmd, "pid": proc.pid, "start": time.time()}

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            exit_code = proc.returncode
        except asyncio.TimeoutError:
            timed_out = True
            proc.kill()
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=5)
            except asyncio.TimeoutError:
                stdout_bytes, stderr_bytes = b"", b""
            exit_code = proc.returncode if proc.returncode is not None else -1

        duration = round(time.time() - t0, 3)

        # Decode output
        stdout = decode_output(stdout_bytes) if stdout_bytes else ""
        stderr = decode_output(stderr_bytes) if stderr_bytes else ""

        # Truncate if needed
        truncated = False
        if len(stdout.encode("utf-8", "replace")) > max_output:
            stdout = stdout.encode("utf-8", "replace")[:max_output].decode("utf-8", "replace")
            truncated = True
        if len(stderr.encode("utf-8", "replace")) > max_output:
            stderr = stderr.encode("utf-8", "replace")[:max_output].decode("utf-8", "replace")
            truncated = True

        stdout_bytes_len = len(stdout_bytes) if stdout_bytes else 0
        stderr_bytes_len = len(stderr_bytes) if stderr_bytes else 0

        ok = (not timed_out) and exit_code == 0
        event_type = "exec_timeout" if timed_out else "exec_done"
        audit({"type": event_type, "request_id": request_id, "cmd": cmd, "exit_code": exit_code,
                "duration": duration, "truncated": truncated,
                "stdout_bytes": stdout_bytes_len, "stderr_bytes": stderr_bytes_len})

        _record_request(duration=duration, is_exec=True, is_error=not ok)
        return _cors_json_response({
            "ok": ok,
            "request_id": request_id,
            "exit_code": exit_code,
            "duration_sec": duration,
            "cwd": str(cwd),
            "stdout": stdout,
            "stderr": stderr,
            "truncated": truncated,
            "stdout_bytes": stdout_bytes_len,
            "stderr_bytes": stderr_bytes_len,
            "error": f"timeout after {timeout}s" if timed_out else None,
        }, status=408 if timed_out else 200)

    except Exception as e:
        duration = round(time.time() - t0, 3)
        audit({"type": "exec_error", "request_id": request_id, "cmd": cmd, "duration": duration, "error": repr(e)})
        _record_request(duration=duration, is_exec=True, is_error=True)
        return _cors_json_response({"ok": False, "request_id": request_id, "error": repr(e), "duration_sec": duration}, status=500)

    finally:
        ACTIVE_PROCESSES.pop(request_id, None)
        cfg["active_exec"] -= 1
        sem.release()


async def handle_v1_kill(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    try:
        data = await request.json()
    except Exception:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "invalid json"}, status=400)
    target_id = data.get("request_id")
    if not target_id or target_id not in ACTIVE_PROCESSES:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "process not found"}, status=404)
    info = ACTIVE_PROCESSES[target_id]
    try:
        os.kill(info["pid"], signal.SIGTERM if os.name != "nt" else signal.CTRL_BREAK_EVENT)
    except Exception:
        pass
    audit({"type": "process_killed", "target_request_id": target_id, "client": request.remote or "127.0.0.1"})
    _record_request()
    return _cors_json_response({"ok": True, "killed": target_id})


async def handle_v1_upload(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    qs = parse_qs(request.query_string)
    target = qs.get("path", [""])[0]
    if not target:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing path"}, status=400)
    # Path traversal protection
    if ".." in Path(target).parts:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "path traversal not allowed"}, status=400)
    target_path = Path(target).expanduser()
    if not target_path.is_absolute():
        target_path = request.app["cfg"]["root"] / target_path
    # Prevent overwriting bridge itself or writing outside user home
    try:
        target_path.resolve().relative_to(Path.home())
    except ValueError:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "upload path must be inside user home"}, status=403)
    bridge_py = Path(__file__).resolve()
    if target_path.resolve() == bridge_py.resolve():
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "cannot overwrite the bridge itself"}, status=403)
    # Reject multipart form-data uploads (they corrupt file content)
    ct = request.headers.get("Content-Type", "")
    if "multipart" in ct.lower():
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "multipart/form-data not supported; use --data-binary"}, status=400)
    try:
        body = await request.read()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(body)
        audit({"type": "file_upload", "path": str(target_path), "bytes": len(body)})
        _record_request()
        return _cors_json_response({"ok": True, "path": str(target_path), "bytes": len(body)})
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": repr(e)}, status=500)


async def handle_v1_download(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    qs = parse_qs(request.query_string)
    target = qs.get("path", [""])[0]
    if not target:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing path"}, status=400)
    if ".." in Path(target).parts:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "path traversal not allowed"}, status=400)
    target_path = Path(target).expanduser()
    if not target_path.is_absolute():
        target_path = request.app["cfg"]["root"] / target_path
    if not target_path.exists() or not target_path.is_file():
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "file not found"}, status=404)
    try:
        audit({"type": "file_download", "path": str(target_path), "bytes": target_path.stat().st_size})
        _record_request()
        return web.FileResponse(target_path, headers={
            "Content-Disposition": f'attachment; filename="{target_path.name}"',
            "Access-Control-Allow-Origin": "*",
        })
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": repr(e)}, status=500)


# ============================================================================
# HANDLER — Dashboard GUI
# ============================================================================

async def handle_gui(request: web.Request) -> web.Response:
    try:
        cfg = request.app["cfg"]
        # Try multiple locations for the dashboard
        candidates = [
            BRIDGE_DIR / "dashboard" / "index.html",
            BRIDGE_DIR / "index.html",
        ]
        for html_path in candidates:
            if html_path.exists():
                html = html_path.read_text(encoding="utf-8")
                html = html.replace("{{TOKEN}}", cfg["token"])
                html = html.replace("{{VERSION}}", VERSION)
                html = html.replace("{{HOST}}", socket.gethostname())
                return web.Response(text=html, content_type="text/html", charset="utf-8",
                                    headers={"Access-Control-Allow-Origin": "*"})
        # Fallback: generate a minimal dashboard
        fallback = f"""<!DOCTYPE html><html><head><title>Arena Bridge v{VERSION}</title></head>
        <body style='font-family:monospace;background:#1a1a2e;color:#e0e0e0;padding:2rem'>
        <h1>Arena Unified Bridge v{VERSION}</h1><p>Dashboard not found.</p>
        <p>API: <a href='/'>/</a> | Health: <a href='/health'>/health</a></p>
        <p>Token: <code>{cfg['token'][:8]}...</code></p>
        </body></html>"""
        return web.Response(text=fallback, content_type="text/html", charset="utf-8",
                            headers={"Access-Control-Allow-Origin": "*"})
    except Exception as e:
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# ============================================================================
# HANDLERS — Dashboard API endpoints
# ============================================================================

def _load_facts() -> list[dict]:
    """Load memory facts from JSONL. Deduplicates by key (last write wins)."""
    if not MEMORY_FILE.exists():
        return []
    seen: dict[str, dict] = {}
    order: list[str] = []
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        item = json.loads(line)
                        key = item.get("key", "")
                        if key not in seen:
                            order.append(key)
                        seen[key] = item
                    except json.JSONDecodeError:
                        pass
    except Exception:
        pass
    return [seen[k] for k in order if k in seen]


def _write_fact(entry: dict) -> None:
    """Write a fact entry, overwriting any existing entry with the same key."""
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_facts()
    key = entry.get("key", "")
    existing = [f for f in existing if f.get("key") != key]
    existing.append(entry)
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        for fact in existing:
            f.write(json.dumps(fact, ensure_ascii=False) + "\n")


async def handle_v1_memory(request: web.Request) -> web.Response:
    """GET /v1/memory — list memory facts. Optional ?q=filter."""
    try:
        r = require_auth(request)
        if r: return r
        _record_request()
        loop = asyncio.get_event_loop()
        facts = await loop.run_in_executor(_EXECUTOR, _load_facts)
        qs = parse_qs(request.query_string)
        q = qs.get("q", [""])[0].lower()
        if q:
            facts = [f for f in facts if q in json.dumps(f, ensure_ascii=False).lower()]
        return _cors_json_response({"ok": True, "count": len(facts), "facts": facts[-100:]})
    except Exception as e:
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_memory_set(request: web.Request) -> web.Response:
    """POST /v1/memory — set a memory fact. Body: {key, value, tags?}."""
    r = require_auth(request)
    if r: return r
    _record_request()
    try:
        data = await request.json()
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": f"invalid json: {e}"}, status=400)
    key = str(data.get("key", "")).strip()
    value = str(data.get("value", "")).strip()
    if not key:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing key"}, status=400)
    tags = data.get("tags") or []
    entry = {
        "key": key, "value": value, "tags": tags,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(_EXECUTOR, _write_fact, entry)
    return _cors_json_response({"ok": True, "fact": entry})


def _list_missions_sync() -> list[dict]:
    """Synchronous helper to list missions with stat() calls."""
    missions = []
    if MISSIONS_DIR.exists():
        for m in sorted(MISSIONS_DIR.iterdir()):
            if m.is_file() and m.suffix in (".json", ".yaml", ".yml", ".md", ".txt"):
                missions.append({
                    "name": m.stem, "ext": m.suffix, "size": m.stat().st_size,
                    "modified": datetime.fromtimestamp(m.stat().st_mtime, tz=timezone.utc).isoformat(),
                })
            elif m.is_dir():
                missions.append({
                    "name": m.name, "ext": "[dir]",
                    "size": len(list(m.iterdir())),
                    "modified": datetime.fromtimestamp(m.stat().st_mtime, tz=timezone.utc).isoformat(),
                })
    return missions


async def handle_v1_missions(request: web.Request) -> web.Response:
    """GET /v1/missions — list missions."""
    try:
        r = require_auth(request)
        if r: return r
        _record_request()
        loop = asyncio.get_event_loop()
        missions = await loop.run_in_executor(_EXECUTOR, _list_missions_sync)
        return _cors_json_response({"ok": True, "count": len(missions), "missions": missions})
    except Exception as e:
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


def _winsound_melody() -> None:
    """Play a melody using winsound (blocking, runs in executor)."""
    import winsound
    for f, d in [(523, 150), (659, 150), (784, 150), (1047, 300)]:
        winsound.Beep(f, d)


async def handle_v1_beep(request: web.Request) -> web.Response:
    """POST /v1/beep — play a sound notification. Body: {type?, frequency?, duration?}."""
    r = require_auth(request)
    if r: return r
    _record_request()
    try:
        data = await request.json()
    except Exception:
        data = {}
    beep_type = data.get("type", "success")
    presets = {"success": (800, 300), "warning": (600, 500), "error": (400, 700), "attention": (1000, 200)}
    freq, dur = presets.get(beep_type, (800, 300))
    freq = int(data.get("frequency", freq))
    dur = int(data.get("duration", dur))

    if sys.platform == "win32":
        try:
            import winsound
            loop = asyncio.get_event_loop()
            if beep_type == "melody":
                await loop.run_in_executor(_EXECUTOR, _winsound_melody)
            else:
                await loop.run_in_executor(_EXECUTOR, winsound.Beep, freq, dur)
            return _cors_json_response({"ok": True, "type": beep_type, "frequency": freq, "duration": dur})
        except Exception as e:
            return _cors_json_response({"ok": False, "error": str(e)})
    else:
        # Linux: try beep command or terminal bell
        try:
            import shutil
            if shutil.which("beep"):
                await asyncio.get_event_loop().run_in_executor(_EXECUTOR, subprocess.run, ["beep", "-f", str(freq), "-l", str(dur)], True, True, 5)
                return _cors_json_response({"ok": True, "type": beep_type})
        except Exception:
            pass
        # Fallback: terminal bell (won't work in HTTP context, but try)
        return _cors_json_response({"ok": True, "type": beep_type, "note": "no sound device, simulated"})


def _check_internet_sync() -> bool:
    """Synchronous internet check — returns True if reachable."""
    import urllib.request
    try:
        urllib.request.urlopen("https://www.google.com", timeout=3)
        return True
    except Exception:
        return False


async def handle_v1_doctor(request: web.Request) -> web.Response:
    """GET /v1/doctor — run diagnostics."""
    r = require_auth(request)
    if r: return r
    _record_request()
    checks = []
    # Bridge
    checks.append({"name": "Bridge running", "ok": True, "detail": f"v{VERSION}"})
    # Token
    token = request.app["cfg"]["token"]
    checks.append({"name": "Token", "ok": bool(token), "detail": f"{len(token)} chars" if token else "missing"})
    # Python
    checks.append({"name": "Python", "ok": True, "detail": sys.version.split()[0]})
    # Directories
    for name, path in [("Bridge dir", BRIDGE_DIR),
                        ("Memory dir", MEMORY_FILE.parent), ("Missions dir", MISSIONS_DIR)]:
        checks.append({"name": name, "ok": path.exists(), "detail": str(path)})
    # Memory
    loop = asyncio.get_event_loop()
    facts = await loop.run_in_executor(_EXECUTOR, _load_facts)
    checks.append({"name": "Memory facts", "ok": len(facts) > 0, "detail": f"{len(facts)} entries"})
    # Internet
    internet_ok = await loop.run_in_executor(_EXECUTOR, _check_internet_sync)
    checks.append({"name": "Internet", "ok": internet_ok, "detail": "available" if internet_ok else "not reachable"})
    # Sound
    if sys.platform == "win32":
        try:
            import winsound
            checks.append({"name": "Sound", "ok": True, "detail": "winsound available"})
        except ImportError:
            checks.append({"name": "Sound", "ok": False, "detail": "winsound not available"})
    else:
        import shutil
        checks.append({"name": "Sound", "ok": bool(shutil.which("beep") or shutil.which("paplay")), "detail": ""})
    # Disk
    try:
        import shutil as _shutil
        disk = _shutil.disk_usage(str(Path.home()))
        checks.append({"name": "Disk free", "ok": disk.free > 1024**3, "detail": f"{disk.free // (1024**3)} GB"})
    except Exception:
        pass

    passed = sum(1 for c in checks if c["ok"])
    return _cors_json_response({"ok": True, "passed": passed, "total": len(checks), "checks": checks})


def _list_reports_sync() -> list[dict]:
    """Synchronous helper to list reports with stat() calls."""
    reports = []
    if REPORTS_DIR.exists():
        for r_file in sorted(REPORTS_DIR.iterdir()):
            if r_file.is_file():
                reports.append({
                    "name": r_file.name, "size": r_file.stat().st_size,
                    "modified": datetime.fromtimestamp(r_file.stat().st_mtime, tz=timezone.utc).isoformat(),
                })
    # Also check shots subdirectory
    shots_dir = REPORTS_DIR / "shots"
    if shots_dir.exists():
        for s in sorted(shots_dir.iterdir()):
            if s.is_file():
                reports.append({
                    "name": f"shots/{s.name}", "size": s.stat().st_size,
                    "modified": datetime.fromtimestamp(s.stat().st_mtime, tz=timezone.utc).isoformat(),
                })
    return reports


async def handle_v1_reports(request: web.Request) -> web.Response:
    """GET /v1/reports — list reports."""
    try:
        r = require_auth(request)
        if r: return r
        _record_request()
        loop = asyncio.get_event_loop()
        reports = await loop.run_in_executor(_EXECUTOR, _list_reports_sync)
        return _cors_json_response({"ok": True, "count": len(reports), "reports": reports})
    except Exception as e:
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


def _browser_search_sync(query: str, n: int) -> dict:
    """Synchronous DuckDuckGo search — returns dict result."""
    import urllib.parse as _up
    import urllib.request
    import html as _html
    import re as _re
    url = f"https://html.duckduckgo.com/html/?q={_up.quote_plus(query)}"
    req_obj = urllib.request.Request(url)
    req_obj.add_header("User-Agent", "ArenaBridge/1.5")
    with urllib.request.urlopen(req_obj, timeout=15) as resp:
        content = resp.read().decode("utf-8", errors="replace")
    results = []
    link_pat = _re.compile(r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', _re.DOTALL)
    snippet_pat = _re.compile(r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', _re.DOTALL)
    links = link_pat.findall(content)
    snippets = snippet_pat.findall(content)
    for i, (href, title) in enumerate(links[:n]):
        title_clean = _re.sub(r'<[^>]+>', '', title).strip()
        uddg = _re.search(r'uddg=([^&]+)', href)
        real_url = _up.unquote(uddg.group(1)) if uddg else href
        snippet = _re.sub(r'<[^>]+>', '', snippets[i]).strip() if i < len(snippets) else ""
        results.append({"title": title_clean, "url": real_url, "snippet": snippet})
    return {"ok": True, "query": query, "count": len(results), "results": results}


async def handle_v1_browser_search(request: web.Request) -> web.Response:
    """GET /v1/browser/search?q=query&n=5 — search DuckDuckGo."""
    r = require_auth(request)
    if r: return r
    _record_request()
    qs = parse_qs(request.query_string)
    query = qs.get("q", [""])[0]
    n = int(qs.get("n", ["5"])[0])
    if not query:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing q parameter"}, status=400)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _browser_search_sync, query, n)
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


def _validate_url(url: str) -> str | None:
    """Validate URL scheme for browser endpoints. Returns error message or None."""
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
    except Exception:
        return "invalid URL"
    if parsed.scheme not in ("http", "https"):
        return f"URL scheme '{parsed.scheme}' not allowed (only http/https)"
    hostname = parsed.hostname or ""
    if hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
        return "localhost/internal URLs not allowed"
    if hostname.startswith("169.254."):
        return "cloud metadata URLs not allowed"
    if hostname.startswith("10.") or hostname.startswith("192.168."):
        return "private network URLs not allowed"
    return None


def _browser_read_sync(url: str) -> dict:
    """Synchronous URL read with readability extraction — returns dict result."""
    err = _validate_url(url)
    if err:
        return {"ok": False, "error": err}
    import urllib.request
    import re as _re
    import html as _html
    req_obj = urllib.request.Request(url)
    req_obj.add_header("User-Agent", "ArenaBridge/1.5")
    with urllib.request.urlopen(req_obj, timeout=15) as resp:
        content = resp.read().decode("utf-8", errors="replace")
    # Extract title
    title = ""
    m = _re.search(r'<title[^>]*>(.*?)</title>', content, _re.IGNORECASE | _re.DOTALL)
    if m:
        title = _re.sub(r'<[^>]+>', '', m.group(1)).strip()
    # Remove script/style/nav/footer
    for tag in ["script", "style", "nav", "footer", "header", "aside", "noscript"]:
        content = _re.sub(f'<{tag}[^>]*>.*?</{tag}>', '', content, flags=_re.DOTALL | _re.IGNORECASE)
    # Try to find main content
    main = ""
    for sel in [r'<article[^>]*>(.*?)</article>', r'<main[^>]*>(.*?)</main>']:
        match = _re.search(sel, content, _re.DOTALL | _re.IGNORECASE)
        if match:
            main = match.group(1)
            break
    if not main:
        main = content
    text = _re.sub(r'<[^>]+>', ' ', main)
    text = _html.unescape(text)
    text = _re.sub(r'\s+', ' ', text).strip()
    # Limit output
    if len(text) > 20000:
        text = text[:20000] + "\n...[truncated]"
    return {"ok": True, "title": title, "url": url, "text": text, "length": len(text)}


async def handle_v1_browser_read(request: web.Request) -> web.Response:
    """GET /v1/browser/read?url=URL — readability-extract text from URL."""
    r = require_auth(request)
    if r: return r
    _record_request()
    qs = parse_qs(request.query_string)
    url = qs.get("url", [""])[0]
    if not url:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing url parameter"}, status=400)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _browser_read_sync, url)
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# ============================================================================
# HANDLERS — v1.5.0 New Endpoints
# ============================================================================

# --- /v1/service/info GET — What manages this bridge process? ---

def _service_info_sync() -> dict:
    """Detect under what service manager (NSSM/Scheduled Task/systemd/launchd/none) we run."""
    result: dict[str, Any] = {"ok": True, "running_as": "unknown"}
    if sys.platform == "win32":
        svc_name = os.environ.get("ARENA_SERVICE_NAME", "").strip() or "ArenaUnifiedBridge"
        result["candidate_service"] = svc_name
        # 1. NSSM/SCM (locale-agnostic)
        exists, raw, running = _sc_query_running(svc_name)
        if exists:
            result["nssm_service"] = {
                "exists": True,
                "running": running,
                "raw": raw[:800],
            }
            if running:
                result["running_as"] = "nssm-service"
            else:
                result["running_as"] = "nssm-service-stopped"
        # 2. Scheduled Task
        try:
            r = subprocess.run(["schtasks", "/Query", "/TN", svc_name],
                               capture_output=True, text=True, timeout=5,
                               **_subprocess_kwargs())
            if r.returncode == 0:
                result["scheduled_task"] = {"exists": True, "raw": (r.stdout or "")[:400]}
                if result.get("running_as") == "unknown":
                    result["running_as"] = "scheduled-task"
        except Exception:
            pass
    elif sys.platform == "linux":
        try:
            r = subprocess.run(["systemctl", "--user", "is-active", "arena-bridge.service"],
                               capture_output=True, text=True, timeout=5,
                               **_subprocess_kwargs())
            if (r.stdout or "").strip() == "active":
                result["running_as"] = "systemd-user"
                result["systemd_user"] = {"active": True, "unit": "arena-bridge.service"}
        except Exception:
            pass
    elif sys.platform == "darwin":
        try:
            r = subprocess.run(["launchctl", "print", "gui/0/com.arena.bridge"],
                               capture_output=True, text=True, timeout=5,
                               **_subprocess_kwargs())
            if r.returncode == 0:
                result["running_as"] = "launchd"
                result["launchd"] = {"loaded": True}
        except Exception:
            pass

    # PID info — always include
    result["pid"] = os.getpid()
    result["python"] = sys.executable
    return result


async def handle_v1_service_info(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    _record_request()
    try:
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(_EXECUTOR, _service_info_sync)
        return _cors_json_response(info)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)



def _sc_query_running(svc_name: str) -> tuple[bool, str, bool]:
    """Run `sc query <name>` and return (exists, raw_output, running).
    Locale-agnostic: looks for the numeric state code `STATE` line containing
    "4" (RUNNING), in addition to any RUNNING substring.
    """
    try:
        r = subprocess.run(
            ["sc", "query", svc_name],
            capture_output=True, text=True, timeout=5,
            **_subprocess_kwargs(),
        )
    except Exception:
        return False, "", False
    out = (r.stdout or "") + (r.stderr or "")
    # `sc query` exits 1060 (ERROR_SERVICE_DOES_NOT_EXIST) -> no service
    if r.returncode == 1060 or "1060" in out:
        return False, out, False
    # Locale-agnostic checks
    # English: "STATE              : 4  RUNNING"
    # Russian: "Состояние          : 4  RUNNING"   (RUNNING is always English)
    # German:  "ZUSTAND            : 4  RUNNING"
    # Italian: "STATO              : 4  RUNNING"
    # etc. — "RUNNING" is constant; numeric state code `: 4 ` is constant.
    up = out.upper()
    running = ("RUNNING" in up) or (": 4 " in out) or (": 4\t" in out)
    # heuristic: presence of "_NAME" / numeric STATE row means service exists
    exists = (": 4 " in out) or (": 1 " in out) or (": 2 " in out) or (": 3 " in out) \
             or (": 5 " in out) or (": 6 " in out) or (": 7 " in out) \
             or ("RUNNING" in up) or ("STOPPED" in up) or ("PAUSED" in up) \
             or ("PENDING" in up)
    return exists, out, running


# --- /v1/sys/svc GET — Service status ---

def _sys_svc_sync() -> dict:
    """Synchronous helper to check service status."""
    result: dict[str, Any] = {"ok": True}

    if sys.platform == "win32":
        # 1) NSSM / Windows Service Manager detection (locale-agnostic)
        nssm_running = False
        nssm_detail = ""
        svc_name = os.environ.get("ARENA_SERVICE_NAME", "").strip() or "ArenaUnifiedBridge"
        exists, raw, running = _sc_query_running(svc_name)
        if exists:
            if running:
                nssm_running = True
                nssm_detail = f'Service "{svc_name}" RUNNING (NSSM/SCM)'
            else:
                nssm_detail = f'Service "{svc_name}" present but not RUNNING'
        else:
            nssm_detail = f'Service "{svc_name}" not registered'
        result["windows_service"] = {"running": nssm_running, "detail": nssm_detail}

        # 2) Scheduled Task detection
        scheduled_task = False
        scheduled_detail = ""
        task_names = [os.environ.get("ARENA_TASK_NAME", "").strip()] if os.environ.get("ARENA_TASK_NAME") else []
        task_names += ["ArenaUnifiedBridge", "ArenaBridge", "ArenaLocalBridge"]
        seen = set()
        for tname in [n for n in task_names if n and not (n in seen or seen.add(n))]:
            try:
                out = subprocess.check_output(
                    ['schtasks', '/query', '/tn', tname, '/fo', 'LIST'],
                    stderr=subprocess.DEVNULL, **_subprocess_kwargs())
                if tname.encode() in out:
                    scheduled_task = True
                    scheduled_detail = f'Scheduled Task: "{tname}" (registered)'
                    break
            except Exception:
                continue
        if not scheduled_task:
            scheduled_detail = "No matching Windows scheduled task (tried: " + ", ".join(task_names) + ")"

        # If NSSM/Windows service is running, reflect that as the primary scheduled mechanism
        if result.get("windows_service", {}).get("running"):
            scheduled_task = True
            scheduled_detail = result["windows_service"]["detail"]
        result["scheduled_task"] = {"running": scheduled_task, "detail": scheduled_detail}

    elif sys.platform == "darwin":
        # macOS launchd
        launchd_active = False
        launchd_detail = ""
        try:
            out = subprocess.check_output(
                ["launchctl", "print", f"gui/{os.getuid()}/com.arena.bridge"],
                stderr=subprocess.DEVNULL, text=True, **_subprocess_kwargs())
            launchd_active = "running" in out.lower() or "active" in out.lower()
            launchd_detail = "com.arena.bridge loaded"
        except Exception:
            launchd_detail = "launchd service not found"
        result["launchd"] = {"active": launchd_active, "detail": launchd_detail}

    else:
        # Linux — check systemd user service
        sd_active = False
        sd_detail = ""
        try:
            out = subprocess.check_output(
                ["systemctl", "--user", "is-active", "arena-bridge"],
                stderr=subprocess.DEVNULL, **_subprocess_kwargs())
            status = out.decode("utf-8", errors="replace").strip()
            sd_active = (status == "active")
            sd_detail = f"systemd user service: {status}"
        except Exception:
            # Check for cron as fallback
            try:
                out = subprocess.check_output(["crontab", "-l"], stderr=subprocess.DEVNULL, **_subprocess_kwargs())
                if b"unified_bridge" in out or b"arena" in out:
                    sd_active = True
                    sd_detail = "cron job found"
                else:
                    sd_detail = "No cron/systemd service"
            except Exception:
                sd_detail = "No service detected"
        result["systemd_user"] = {"active": sd_active, "detail": sd_detail}

    # Check running bridge processes
    bridge_procs = []
    try:
        if sys.platform == "win32":
            out = subprocess.check_output(
                'wmic process where "commandline like \'%unified_bridge%\'" get processid,commandline /format:list',
                shell=True, stderr=subprocess.DEVNULL, text=True, **_subprocess_kwargs())
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("CommandLine=") or line.startswith("ProcessId="):
                    bridge_procs.append(line)
        else:
            out = subprocess.check_output(
                ["ps", "aux"], stderr=subprocess.DEVNULL, text=True, **_subprocess_kwargs())
            for line in out.splitlines():
                if "unified_bridge" in line and "grep" not in line:
                    bridge_procs.append(line.strip()[:200])
    except Exception:
        pass
    result["bridge_processes"] = {"count": len(bridge_procs), "details": bridge_procs[:10]}

    # Check Tailscale status
    tailscale = {"installed": False, "connected": False, "detail": ""}
    try:
        out = subprocess.check_output(["tailscale", "status"], stderr=subprocess.DEVNULL, text=True, **_subprocess_kwargs())
        tailscale["installed"] = True
        tailscale["connected"] = bool(out.strip())
        tailscale["detail"] = out.strip()[:500]
    except FileNotFoundError:
        tailscale["detail"] = "tailscale not found"
    except Exception as e:
        tailscale["installed"] = True
        tailscale["detail"] = str(e)[:200]
    result["tailscale"] = tailscale

    return result


async def handle_v1_sys_svc(request: web.Request) -> web.Response:
    """GET /v1/sys/svc — Service status."""
    r = require_auth(request)
    if r: return r
    _record_request()
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _sys_svc_sync)
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/sys/funnel GET — Tailscale Funnel status ---

def _sys_funnel_sync() -> dict:
    """Synchronous helper to check Tailscale funnel status."""
    result: dict[str, Any] = {"ok": True, "tailscale": {}, "funnel": {}}

    # Run tailscale status
    try:
        out = subprocess.check_output(["tailscale", "status"], stderr=subprocess.STDOUT, text=True, **_subprocess_kwargs())
        result["tailscale"]["status"] = out.strip()[:2000]
        result["tailscale"]["connected"] = bool(out.strip())
    except FileNotFoundError:
        result["tailscale"]["error"] = "tailscale not found"
    except Exception as e:
        result["tailscale"]["error"] = str(e)[:500]

    # Run tailscale funnel status
    try:
        out = subprocess.check_output(["tailscale", "funnel", "status"], stderr=subprocess.STDOUT, text=True, **_subprocess_kwargs())
        result["funnel"]["status"] = out.strip()[:2000]
        _lw = out.lower()
        result["funnel"]["active"] = (
            "funnel on" in _lw
            or "proxy http" in _lw
            or "serving" in _lw
            or "listening" in _lw
        )
        # extract public URL if present (https://*.ts.net)
        m = re.search(r"https://[\w.-]+\.ts\.net[^\s]*", out)
        if m:
            result["funnel"]["url"] = m.group(0)
    except FileNotFoundError:
        result["funnel"]["error"] = "tailscale not found"
    except Exception as e:
        result["funnel"]["error"] = str(e)[:500]

    return result


async def handle_v1_sys_funnel(request: web.Request) -> web.Response:
    """GET /v1/sys/funnel — Tailscale Funnel status."""
    r = require_auth(request)
    if r: return r
    _record_request()
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _sys_funnel_sync)
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/token/regenerate POST — Generate new auth token ---

def _token_path() -> Path:
    """Resolve token file location used by start-bridge / install.bat."""
    return Path(os.environ.get("ARENA_TOKEN_FILE",
                str(TOKEN_FILE))).expanduser()


def _token_regen_sync(target_path: str = "") -> dict:
    """Generate a new token and write it to ONLY the bridge's own token.txt.
    Path resolution priority:
      1. explicit target_path arg (from cfg["token_file"] or env)
      2. ARENA_TOKEN_FILE env var
      3. <BRIDGE_DIR from sys.argv 'serve --root'>/token.txt — best effort
      4. ~/arena-bridge/token.txt  (default)
    NEVER writes to multiple locations — that risks clobbering another instance's token.
    """
    import secrets, base64
    new_tok = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")

    target: Path
    if target_path:
        target = Path(target_path).expanduser()
    else:
        env = os.environ.get("ARENA_TOKEN_FILE")
        if env:
            target = Path(env).expanduser()
        else:
            # Default to the canonical bridge-dir token file
            target = TOKEN_FILE

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(new_tok, encoding="utf-8")
        try:
            os.chmod(target, 0o600)
        except Exception:
            pass
        return {
            "ok": True,
            "token": new_tok,
            "written_to": [str(target)],
            "note": ("Existing connections still use the OLD token until the bridge restarts. "
                     "Use POST /v1/restart, or click Restart Bridge."),
        }
    except Exception as e:
        return {"ok": False, "error": f"Failed to write {target}: {e}"}


async def handle_v1_token_regenerate(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    _record_request()
    cfg = request.app["cfg"]
    # Prefer the exact token_file that this bridge instance reads on startup
    target = str(cfg.get("token_file") or "")
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _token_regen_sync, target)
        # Hot-update in-memory token so new requests accept it immediately
        if result.get("ok") and result.get("token"):
            cfg["token"] = result["token"]
        audit({"type": "token_regenerated", "files": result.get("written_to", [])})
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/tailscale/funnel/{action} POST — start | stop | status ---

def _tailscale_funnel_action_sync(action: str, port: int) -> dict:
    import subprocess as _sp
    import shutil as _shutil_local
    action = (action or "").lower()
    if action not in ("start", "stop", "status"):
        return {"ok": False, "error": "action must be start|stop|status"}
    # locate tailscale
    ts = _shutil_local.which("tailscale")
    if not ts and platform.system() == "Windows":
        candidates = [
            r"C:\Program Files\Tailscale\tailscale.exe",
            r"C:\Program Files (x86)\Tailscale\tailscale.exe",
        ]
        for c in candidates:
            if os.path.isfile(c):
                ts = c; break
    if not ts:
        return {"ok": False, "error": "tailscale binary not found"}

    if action == "start":
        # `tailscale funnel --bg 8765`
        try:
            r = _sp.run([ts, "funnel", "--bg", str(port)],
                        capture_output=True, text=True, timeout=15)
            return {"ok": r.returncode == 0, "action": "start", "port": port,
                    "stdout": r.stdout, "stderr": r.stderr,
                    "exit_code": r.returncode}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    if action == "stop":
        # `tailscale funnel --https=443 off`
        try:
            r = _sp.run([ts, "funnel", "--https=443", "off"],
                        capture_output=True, text=True, timeout=15)
            return {"ok": r.returncode == 0, "action": "stop",
                    "stdout": r.stdout, "stderr": r.stderr,
                    "exit_code": r.returncode}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    # status
    try:
        r = _sp.run([ts, "funnel", "status"],
                    capture_output=True, text=True, timeout=10)
        out = r.stdout or ""
        return {"ok": True, "action": "status", "output": out,
                "active": ("funnel on" in out.lower() or "proxy http" in out.lower())}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def handle_v1_tailscale_funnel(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    _record_request()
    action = request.match_info.get("action", "status")
    cfg = request.app["cfg"]
    port = cfg.get("port", 8765)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _tailscale_funnel_action_sync, action, port)
        audit({"type": "tailscale_funnel", "action": action, "ok": result.get("ok")})
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/restart POST — Graceful shutdown (scheduled task / systemd / launchd will respawn) ---

def _spawn_respawn_helper(port: int) -> tuple[bool, str]:
    """Spawn a detached helper script that waits ~2s, then re-launches the bridge.

    Drops a script file in TEMP and launches it via the platform's native
    detached-process mechanism, so the helper survives os._exit() of the parent.

    Returns (ok, method_used).
    """
    import subprocess as _sp
    import tempfile
    sys_name = platform.system()
    bridge_dir = Path(__file__).resolve().parent
    bridge_py = str(Path(__file__).resolve())
    task_name = os.environ.get("ARENA_TASK_NAME", "ArenaUnifiedBridge")
    token_file = str(bridge_dir / "token.txt")

    if sys_name == "Windows":
        # First try: is there an NSSM/SCM-managed service? If yes, just `net start` it after exit.
        svc_name = os.environ.get("ARENA_SERVICE_NAME", "").strip() or "ArenaUnifiedBridge"
        svc_exists = False
        try:
            r = _sp.run(["sc", "query", svc_name],
                        capture_output=True, text=True, timeout=5,
                        **_subprocess_kwargs())
            svc_exists = "SERVICE_NAME" in (r.stdout or "")
        except Exception:
            pass
        if svc_exists:
            # NSSM auto-restarts on its own when the process exits. We just wait & exit.
            # Drop a one-shot script that double-checks: if /health still down after 8s, force-start the service.
            import tempfile
            sh_path = Path(tempfile.gettempdir()) / f"arena_nssm_kick_{os.getpid()}.bat"
            # Use a template + replace to avoid PowerShell-style quote/brace hell
            sh_template = r"""@echo off
timeout /t 8 /nobreak >nul
curl -s -o nul -w "%{http_code}" http://127.0.0.1:__PORT__/health > "%TEMP%rena_kick_hc.txt" 2>nul
set /p HC=<"%TEMP%rena_kick_hc.txt"
del "%TEMP%rena_kick_hc.txt" >nul 2>&1
if not "%HC%"=="200" (
    sc start __SVC__ >nul 2>&1
)
(goto) 2>nul & del "%~f0"
"""
            sh = (sh_template
                  .replace("__PORT__", str(port))
                  .replace("__SVC__", svc_name)
                  .replace("\n", "\r\n"))
            try:
                sh_path.write_text(sh, encoding="ascii", newline="")
                DETACHED = 0x00000008
                CNPG = 0x00000200
                _sp.Popen(
                    ["cmd.exe", "/c", "start", "", "/B", str(sh_path)],
                    creationflags=DETACHED | CNPG,
                    stdin=_sp.DEVNULL, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
                    close_fds=True, shell=False,
                )
                return True, f"NSSM auto-restart (service={svc_name})"
            except Exception as e:
                return False, f"NSSM spawn failed: {e}"

        # Fallback: Scheduled Task / direct python launch via .bat
        # Generate .bat with placeholders, then substitute (avoids escape hell)
        BAT_TEMPLATE = r"""@echo off
timeout /t 2 /nobreak >nul
REM Try Scheduled Task first
set "ARENA_TASK=__TASK__"
schtasks /Query /TN "%ARENA_TASK%" >nul 2>&1
if not errorlevel 1 (
    schtasks /End /TN "%ARENA_TASK%" >nul 2>&1
    timeout /t 1 /nobreak >nul
    schtasks /Run /TN "%ARENA_TASK%" >nul 2>&1
)
REM Poll /health for ~12 sec
set TRIES=0
:poll
set /a TRIES+=1
timeout /t 1 /nobreak >nul
curl -s -o nul -w "%%{http_code}" http://127.0.0.1:__PORT__/health > "%TEMP%rena_hc_chk.txt" 2>nul
set /p HC=<"%TEMP%rena_hc_chk.txt"
del "%TEMP%rena_hc_chk.txt" >nul 2>&1
if "%HC%"=="200" goto :cleanup
if %TRIES% LSS 12 goto :poll
REM Last-resort: launch pythonw directly with token from file
set "TOK="
if exist "__TOKEN_FILE__" set /p TOK=<"__TOKEN_FILE__"
set "PYW="
for /f "delims=" %%P in ('where pythonw.exe 2^>nul') do if not defined PYW set "PYW=%%P"
if not defined PYW for /f "delims=" %%P in ('where python.exe 2^>nul') do if not defined PYW set "PYW=%%P"
if defined PYW (
    if defined TOK (
        start "" /B "%PYW%" -u "__BRIDGE__" serve --root "%USERPROFILE%" --profile owner-shell --token "%TOK%" --port __PORT__
    ) else (
        start "" /B "%PYW%" -u "__BRIDGE__" serve --root "%USERPROFILE%" --profile owner-shell --port __PORT__
    )
)
:cleanup
(goto) 2>nul & del "%~f0"
"""
        bat = (BAT_TEMPLATE
               .replace("__TASK__", task_name)
               .replace("__PORT__", str(port))
               .replace("__BRIDGE__", bridge_py)
               .replace("__TOKEN_FILE__", token_file))
        bat_path = Path(tempfile.gettempdir()) / f"arena_respawn_{os.getpid()}.bat"
        try:
            # Use CRLF line endings so cmd parses it cleanly
            bat = bat.replace("\n", "\r\n")
            bat_path.write_text(bat, encoding="ascii", newline="")
            DETACHED = 0x00000008
            CNPG = 0x00000200
            _sp.Popen(
                ["cmd.exe", "/c", "start", "", "/B", str(bat_path)],
                creationflags=DETACHED | CNPG,
                stdin=_sp.DEVNULL, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
                close_fds=True,
                shell=False,
            )
            return True, f"detached .bat (task={task_name}, file={bat_path.name})"
        except Exception as e:
            return False, f"spawn failed: {e}"

    elif sys_name == "Linux":
        SH_TEMPLATE = r"""#!/usr/bin/env bash
sleep 2
if command -v systemctl >/dev/null 2>&1 && systemctl --user list-unit-files arena-bridge.service >/dev/null 2>&1; then
    systemctl --user restart arena-bridge.service
fi
for i in $(seq 1 12); do
    if curl -fsS http://127.0.0.1:__PORT__/health >/dev/null 2>&1; then
        rm -f "$0"; exit 0
    fi
    sleep 1
done
TOK=""
[[ -f "__TOKEN_FILE__" ]] && TOK="$(cat '__TOKEN_FILE__' | tr -d '
 ')"
nohup python3 -u "__BRIDGE__" serve --root "$HOME" --profile owner-shell ${TOK:+--token "$TOK"} --port __PORT__ >/dev/null 2>&1 &
disown
rm -f "$0"
"""
        sh = (SH_TEMPLATE
              .replace("__PORT__", str(port))
              .replace("__BRIDGE__", bridge_py)
              .replace("__TOKEN_FILE__", token_file))
        sh_path = Path(tempfile.gettempdir()) / f"arena_respawn_{os.getpid()}.sh"
        try:
            sh_path.write_text(sh, encoding="utf-8")
            sh_path.chmod(0o755)
            _sp.Popen(["bash", str(sh_path)], start_new_session=True,
                      stdin=_sp.DEVNULL, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
                      close_fds=True)
            return True, f"detached .sh (file={sh_path.name})"
        except Exception as e:
            return False, f"spawn failed: {e}"

    elif sys_name == "Darwin":
        SH_TEMPLATE = r"""#!/usr/bin/env bash
sleep 2
if launchctl print "gui/$UID/com.arena.bridge" >/dev/null 2>&1; then
    launchctl kickstart -k "gui/$UID/com.arena.bridge"
fi
for i in $(seq 1 12); do
    if curl -fsS http://127.0.0.1:__PORT__/health >/dev/null 2>&1; then
        rm -f "$0"; exit 0
    fi
    sleep 1
done
TOK=""
[[ -f "__TOKEN_FILE__" ]] && TOK="$(cat '__TOKEN_FILE__' | tr -d '
 ')"
nohup python3 -u "__BRIDGE__" serve --root "$HOME" --profile owner-shell ${TOK:+--token "$TOK"} --port __PORT__ >/dev/null 2>&1 &
disown
rm -f "$0"
"""
        sh = (SH_TEMPLATE
              .replace("__PORT__", str(port))
              .replace("__BRIDGE__", bridge_py)
              .replace("__TOKEN_FILE__", token_file))
        sh_path = Path(tempfile.gettempdir()) / f"arena_respawn_{os.getpid()}.sh"
        try:
            sh_path.write_text(sh, encoding="utf-8")
            sh_path.chmod(0o755)
            _sp.Popen(["bash", str(sh_path)], start_new_session=True,
                      stdin=_sp.DEVNULL, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
                      close_fds=True)
            return True, f"detached .sh (file={sh_path.name})"
        except Exception as e:
            return False, f"spawn failed: {e}"

    return False, f"unsupported platform: {sys_name}"


async def handle_v1_restart(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    _record_request()
    cfg = request.app["cfg"]
    port = int(cfg.get("port", 8765))
    audit({"type": "restart_requested"})

    # Spawn the respawn helper BEFORE we die
    spawned, method = _spawn_respawn_helper(port)

    # Schedule shutdown after the response is sent
    async def _exit_soon():
        await asyncio.sleep(1.5)
        os._exit(0)
    asyncio.create_task(_exit_soon())

    return _cors_json_response({
        "ok": True,
        "respawn_scheduled": spawned,
        "method": method,
        "shutdown_in_seconds": 1.5,
        "note": ("Bridge shuts down in 1.5s. A detached helper will re-launch it ~3-5s later."
                 if spawned else "WARNING: respawn helper failed to spawn — manual restart required."),
        "manual_restart_hint": (
            "Windows: schtasks /Run /tn ArenaUnifiedBridge | "
            "Linux: systemctl --user restart arena-bridge | "
            "macOS: launchctl kickstart -k gui/$UID/com.arena.bridge"
        ),
    })


# --- /v1/config GET — Token-free configuration dump ---

async def handle_v1_config(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    _record_request()
    cfg = request.app["cfg"]
    return _cors_json_response({
        "ok": True,
        "service": "arena-unified-bridge",
        "version": VERSION,
        "host": socket.gethostname(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "config": {
            "root": str(cfg.get("root", "")),
            "port": cfg.get("port", 8765),
            "profile": cfg.get("profile", "owner-shell"),
            "audit_log": str(cfg.get("audit", "")),
            "max_concurrent": cfg.get("max_concurrent", 3),
            "token_length": len(cfg.get("token", "")) if cfg.get("token") else 0,
            "token_preview": (cfg.get("token", "")[:4] + "..." + cfg.get("token", "")[-4:])
                              if cfg.get("token") and len(cfg["token"]) > 8 else "***",
        },
        "endpoints_total": len([r for r in request.app.router.routes()]),
    })




# --- /v1/browser/dump GET — Full page dump with links ---

def _browser_dump_sync(url: str) -> dict:
    """Fetch URL, extract text + all <a href> links."""
    err = _validate_url(url)
    if err:
        return {"ok": False, "error": err}
    import urllib.request
    import re as _re
    import html as _html

    req_obj = urllib.request.Request(url)
    req_obj.add_header("User-Agent", "ArenaBridge/1.5")
    with urllib.request.urlopen(req_obj, timeout=20) as resp:
        content = resp.read().decode("utf-8", errors="replace")

    # Extract title
    title = ""
    m = _re.search(r'<title[^>]*>(.*?)</title>', content, _re.IGNORECASE | _re.DOTALL)
    if m:
        title = _re.sub(r'<[^>]+>', '', m.group(1)).strip()

    # Extract all links
    links = []
    link_pat = _re.compile(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', _re.DOTALL | _re.IGNORECASE)
    for href, link_text in link_pat.findall(content):
        link_text_clean = _re.sub(r'<[^>]+>', '', link_text).strip()[:200]
        # Skip empty, javascript, and anchor links
        if href and not href.startswith(("javascript:", "#", "mailto:")):
            links.append({"text": link_text_clean, "url": href[:500]})
        if len(links) >= 500:
            break

    # Remove script/style
    for tag in ["script", "style", "noscript"]:
        content = _re.sub(f'<{tag}[^>]*>.*?</{tag}>', '', content, flags=_re.DOTALL | _re.IGNORECASE)

    # Extract text
    text = _re.sub(r'<[^>]+>', ' ', content)
    text = _html.unescape(text)
    text = _re.sub(r'\s+', ' ', text).strip()

    if len(text) > 50000:
        text = text[:50000] + "\n...[truncated]"

    return {"ok": True, "title": title, "url": url, "text": text,
            "links": links[:200], "length": len(text), "link_count": len(links)}


async def handle_v1_browser_dump(request: web.Request) -> web.Response:
    """GET /v1/browser/dump?url=URL — Full page dump with links."""
    r = require_auth(request)
    if r: return r
    _record_request()
    qs = parse_qs(request.query_string)
    url = qs.get("url", [""])[0]
    if not url:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing url parameter"}, status=400)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _browser_dump_sync, url)
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/browser/fetch GET — Raw content fetch ---

def _browser_fetch_sync(url: str) -> dict:
    """Fetch URL, return raw content."""
    err = _validate_url(url)
    if err:
        return {"ok": False, "error": err}
    import urllib.request

    req_obj = urllib.request.Request(url)
    req_obj.add_header("User-Agent", "ArenaBridge/1.5")
    with urllib.request.urlopen(req_obj, timeout=20) as resp:
        raw = resp.read()
        content_type = resp.headers.get("Content-Type", "application/octet-stream")

    # Try to decode as text
    text: str | None = None
    for enc in ["utf-8", "latin-1", "cp1252"]:
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", "replace")

    # Limit output
    truncated = len(text) > 50000
    text = text[:50000]

    return {"ok": True, "url": url, "content_type": content_type,
            "length": len(raw), "text": text, "truncated": truncated}


async def handle_v1_browser_fetch(request: web.Request) -> web.Response:
    """GET /v1/browser/fetch?url=URL — Raw content fetch."""
    r = require_auth(request)
    if r: return r
    _record_request()
    qs = parse_qs(request.query_string)
    url = qs.get("url", [""])[0]
    if not url:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing url parameter"}, status=400)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _browser_fetch_sync, url)
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/browser/head GET — HTTP HEAD ---

def _browser_head_sync(url: str) -> dict:
    """Do HTTP HEAD request, return headers."""
    err = _validate_url(url)
    if err:
        return {"ok": False, "error": err}
    import urllib.request

    req_obj = urllib.request.Request(url, method="HEAD")
    req_obj.add_header("User-Agent", "ArenaBridge/1.5")
    with urllib.request.urlopen(req_obj, timeout=15) as resp:
        headers = dict(resp.headers)
        status_code = resp.status

    return {"ok": True, "url": url, "status_code": status_code, "headers": headers}


async def handle_v1_browser_head(request: web.Request) -> web.Response:
    """GET /v1/browser/head?url=URL — HTTP HEAD request."""
    r = require_auth(request)
    if r: return r
    _record_request()
    qs = parse_qs(request.query_string)
    url = qs.get("url", [""])[0]
    if not url:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing url parameter"}, status=400)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _browser_head_sync, url)
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)



# ============================================================================
# HANDLERS — CDP (Chrome DevTools Protocol)
# ============================================================================

async def _cdp_active_tab(tab_id: Optional[str] = None):
    """Get a CDPTab instance for the given tab_id or the active tab.
    
    Returns (CDPTab, error_response) tuple. If error_response is not None,
    the handler should return it immediately.
    """
    cdp = _get_cdp_module()
    if not cdp:
        return None, _cors_json_response(
            {"ok": False, "error": "cdp_browser module not found. Install to scripts/ directory."},
            status=500
        )
    
    mgr = _cdp_state.get("manager")
    if not mgr or not _cdp_state["connected"]:
        return None, _cors_json_response(
            {"ok": False, "error": "CDP not connected. POST /v1/browser/cdp/connect first."},
            status=400
        )
    
    if tab_id:
        tab = mgr.get_tab(tab_id)
        if not tab:
            return None, _cors_json_response(
                {"ok": False, "error": f"Tab {tab_id} not found"},
                status=404
            )
        if not tab.connected:
            return None, _cors_json_response(
                {"ok": False, "error": f"Tab {tab_id} is not connected"},
                status=400
            )
        return tab, None
    
    # Use active tab
    tab = mgr.active_tab
    if not tab:
        return None, _cors_json_response(
            {"ok": False, "error": "No active tab. Open a tab first."},
            status=400
        )
    if not tab.connected:
        # Try auto-reconnecting the active tab
        try:
            await tab.connect()
        except Exception as e:
            log.warning("[CDP] Auto-reconnect failed for tab %s: %s", tab.target_id, e)
        if not tab.connected:
            return None, _cors_json_response(
                {"ok": False, "error": "Active tab is not connected and auto-reconnect failed. Try POST /v1/browser/cdp/connect again."},
                status=400
            )
    return tab, None


# ---- CDP Session Management ----

async def handle_v1_cdp_status(request):
    """GET /v1/browser/cdp/status — CDP session status."""
    r = require_auth(request)
    if r: return r
    _record_request()
    
    cdp = _get_cdp_module()
    mgr = _cdp_state.get("manager")
    
    status = {
        "ok": True,
        "connected": _cdp_state["connected"],
        "port": _cdp_state["port"],
        "headless": _cdp_state["headless"],
        "module_available": cdp is not None,
        "tab_count": mgr.tab_count if mgr else 0,
        "active_tab_id": mgr.active_tab_id if mgr else None,
        "network_monitoring": _cdp_state.get("monitor") is not None and _cdp_state["monitor"].active if _cdp_state.get("monitor") else False,
        "interception_active": _cdp_state.get("interceptor") is not None and _cdp_state["interceptor"].active if _cdp_state.get("interceptor") else False,
        "cookie_manager_active": _cdp_state.get("cookie_mgr") is not None and _cdp_state["cookie_mgr"].active if _cdp_state.get("cookie_mgr") else False,
    }
    
    if mgr:
        tabs_info = [tab.to_dict() for tab in mgr.list_tabs()]
        status["tabs"] = tabs_info
    
    return _cors_json_response(status)


async def handle_v1_cdp_connect(request):
    """POST /v1/browser/cdp/connect — Connect to browser CDP.
    
    Body (optional JSON):
        port: int (default: 9222)
        headless: bool (default: true)
    """
    global _cdp_connecting
    r = require_auth(request)
    if r: return r
    _record_request()
    
    cdp = _get_cdp_module()
    if not cdp:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response(
            {"ok": False, "error": "cdp_browser module not found. Install to scripts/ directory."},
            status=500
        )
    
    if _cdp_state["connected"]:
        return _cors_json_response({
            "ok": True,
            "message": "Already connected",
            "port": _cdp_state["port"],
            "tab_count": _cdp_state["manager"].tab_count if _cdp_state["manager"] else 0,
        })
    
    if _cdp_connecting:
        return _cors_json_response({"ok": False, "error": "CDP connect already in progress"}, status=409)
    
    # Parse optional body
    port = 9222
    headless = True
    try:
        body = await request.json()
        port = body.get("port", 9222)
        headless = body.get("headless", True)
    except Exception:
        pass
    
    _cdp_connecting = True
    try:
        mgr = cdp.CDPTabManager(port=port, headless=headless, auto_launch=True)
        try:
            await asyncio.wait_for(mgr.connect(), timeout=30)
        except asyncio.TimeoutError:
            _record_request(is_error=True, count_request=False)
            # Check if browser process crashed
            browser_crashed = False
            crash_stderr = ""
            if mgr._browser_proc and mgr._browser_proc.poll() is not None:
                browser_crashed = True
                try:
                    crash_stderr = mgr._browser_proc.stderr.read().decode("utf-8", errors="replace")[:500]
                except Exception:
                    pass
            error_msg = "CDP connect timed out (30s). Browser may not be running or debug port is unreachable."
            if browser_crashed:
                error_msg += f" Browser process crashed (exit code {mgr._browser_proc.returncode})."
                if crash_stderr:
                    error_msg += f" stderr: {crash_stderr}"
            else:
                error_msg += " Try: chromium --remote-debugging-port=9222 --headless=new --no-sandbox &"
            return _cors_json_response(
                {"ok": False, "error": error_msg, "browser_crashed": browser_crashed},
                status=408
            )
        
        _cdp_state["manager"] = mgr
        _cdp_state["connected"] = True
        _cdp_state["port"] = port
        _cdp_state["headless"] = headless
        
        # Verify active tab is actually connected (auto-connect may have failed silently)
        active_tab = mgr.active_tab
        tab_connected = active_tab is not None and active_tab.connected
        if active_tab and not active_tab.connected:
            # Retry connecting to active tab
            try:
                await active_tab.connect()
                tab_connected = True
                log.info("[CDP] Re-connected active tab %s on second attempt", mgr.active_tab_id)
            except Exception as e:
                log.warning("[CDP] Active tab auto-connect failed: %s", e)
        
        result = {
            "ok": True,
            "message": "CDP connected",
            "port": port,
            "headless": headless,
            "tab_count": mgr.tab_count,
            "active_tab_id": mgr.active_tab_id,
            "tabs": [tab.to_dict() for tab in mgr.list_tabs()],
        }
        if not tab_connected:
            result["warning"] = "Active tab is not connected — CDP page operations may fail. Try reconnecting."
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response(
            {"ok": False, "error": f"Failed to connect: {str(e)}"},
            status=500
        )
    finally:
        _cdp_connecting = False


async def handle_v1_cdp_disconnect(request):
    """POST /v1/browser/cdp/disconnect — Disconnect CDP session."""
    global _cdp_connecting
    r = require_auth(request)
    if r: return r
    _record_request()
    
    if not _cdp_state["connected"]:
        return _cors_json_response({"ok": True, "message": "Not connected"})
    
    if _cdp_connecting:
        return _cors_json_response({"ok": False, "error": "CDP operation in progress"}, status=409)
    
    _cdp_connecting = True
    try:
        # Stop monitors/interceptors first
        if _cdp_state.get("interceptor") and _cdp_state["interceptor"].active:
            await _cdp_state["interceptor"].stop()
        if _cdp_state.get("monitor") and _cdp_state["monitor"].active:
            await _cdp_state["monitor"].stop()
        if _cdp_state.get("cookie_mgr") and _cdp_state["cookie_mgr"].active:
            await _cdp_state["cookie_mgr"].stop()
        
        # Close the manager
        if _cdp_state["manager"]:
            await _cdp_state["manager"].close()
        
        _cdp_state["manager"] = None
        _cdp_state["monitor"] = None
        _cdp_state["interceptor"] = None
        _cdp_state["cookie_mgr"] = None
        _cdp_state["connected"] = False
        
        return _cors_json_response({"ok": True, "message": "CDP disconnected"})
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response(
            {"ok": False, "error": f"Disconnect error: {str(e)}"},
            status=500
        )
    finally:
        _cdp_connecting = False


# ---- CDP Page Operations ----

async def handle_v1_cdp_navigate(request):
    """POST /v1/browser/cdp/navigate — Navigate to URL.
    
    Body JSON:
        url: string (required)
        tab_id: string (optional, uses active tab if not specified)
        wait: bool (default: true)
    """
    r = require_auth(request)
    if r: return r
    _record_request()
    
    try:
        body = await request.json()
    except Exception:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)
    
    url = body.get("url")
    if not url:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing 'url' parameter"}, status=400)
    
    tab_id = body.get("tab_id")
    wait = body.get("wait", True)
    
    tab, err = await _cdp_active_tab(tab_id)
    if err: return err
    
    try:
        result = await tab.navigate(url, wait=wait)
        return _cors_json_response({
            "ok": True,
            "url": url,
            "tab_id": tab.target_id,
            "result": result,
        })
    except asyncio.TimeoutError:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response(
            {"ok": False, "error": f"Navigation timed out for {url}"},
            status=408
        )
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response(
            {"ok": False, "error": str(e)},
            status=500
        )


async def handle_v1_cdp_screenshot(request):
    """GET /v1/browser/cdp/screenshot — Take screenshot.
    
    Query params:
        tab_id: string (optional)
        format: "png" | "base64" (default: "base64")
        save_path: string (optional, save to file on host)
    """
    r = require_auth(request)
    if r: return r
    _record_request()
    
    qs = parse_qs(request.query_string)
    tab_id = qs.get("tab_id", [None])[0]
    fmt = qs.get("format", ["base64"])[0]
    save_path = qs.get("save_path", [None])[0]
    
    tab, err = await _cdp_active_tab(tab_id)
    if err: return err
    
    try:
        img_bytes = await tab.screenshot(path=save_path)
        if img_bytes is None:
            _record_request(is_error=True, count_request=False)
            return _cors_json_response({"ok": False, "error": "Screenshot returned no data"}, status=500)
        
        if fmt == "base64":
            import base64 as _b64
            b64_data = _b64.b64encode(img_bytes).decode("ascii")
            return _cors_json_response({
                "ok": True,
                "format": "base64",
                "data": b64_data,
                "size_bytes": len(img_bytes),
                "tab_id": tab.target_id,
            })
        else:
            # Return raw PNG
            return web.Response(
                body=img_bytes,
                content_type="image/png",
                headers={"Access-Control-Allow-Origin": "*"}
            )
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_cdp_dom(request):
    """GET /v1/browser/cdp/dom — Dump page DOM.
    
    Query params:
        tab_id: string (optional)
    """
    r = require_auth(request)
    if r: return r
    _record_request()
    
    qs = parse_qs(request.query_string)
    tab_id = qs.get("tab_id", [None])[0]
    
    tab, err = await _cdp_active_tab(tab_id)
    if err: return err
    
    try:
        html = await tab.dump_dom()
        if html is None:
            _record_request(is_error=True, count_request=False)
            return _cors_json_response({"ok": False, "error": "Failed to dump DOM"}, status=500)
        
        # Truncate if too large
        max_len = DEFAULT_MAX_OUTPUT
        truncated = False
        if len(html) > max_len:
            html = html[:max_len] + f"\n...[truncated {len(html) - max_len} chars]"
            truncated = True
        
        return _cors_json_response({
            "ok": True,
            "html": html,
            "length": len(html),
            "truncated": truncated,
            "tab_id": tab.target_id,
        })
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_cdp_eval(request):
    """POST /v1/browser/cdp/eval — Evaluate JavaScript.
    
    Body JSON:
        expression: string (required)
        tab_id: string (optional)
    """
    r = require_auth(request)
    if r: return r
    _record_request()
    
    try:
        body = await request.json()
    except Exception:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)
    
    expression = body.get("expression")
    if not expression:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing 'expression' parameter"}, status=400)
    
    tab_id = body.get("tab_id")
    tab, err = await _cdp_active_tab(tab_id)
    if err: return err
    
    try:
        result = await tab.eval_js(expression)
        return _cors_json_response({
            "ok": True,
            "result": result,
            "tab_id": tab.target_id,
        })
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_cdp_click(request):
    """POST /v1/browser/cdp/click — Click element by CSS selector.
    
    Body JSON:
        selector: string (required)
        tab_id: string (optional)
    """
    r = require_auth(request)
    if r: return r
    _record_request()
    
    try:
        body = await request.json()
    except Exception:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)
    
    selector = body.get("selector")
    if not selector:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing 'selector' parameter"}, status=400)
    
    tab_id = body.get("tab_id")
    tab, err = await _cdp_active_tab(tab_id)
    if err: return err
    
    try:
        clicked = await tab.click(selector)
        return _cors_json_response({
            "ok": True,
            "clicked": clicked,
            "selector": selector,
            "tab_id": tab.target_id,
        })
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_cdp_type(request):
    """POST /v1/browser/cdp/type — Type text into element.
    
    Body JSON:
        selector: string (required)
        text: string (required)
        tab_id: string (optional)
    """
    r = require_auth(request)
    if r: return r
    _record_request()
    
    try:
        body = await request.json()
    except Exception:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)
    
    selector = body.get("selector")
    text = body.get("text")
    if not selector or text is None:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing 'selector' or 'text' parameter"}, status=400)
    
    tab_id = body.get("tab_id")
    tab, err = await _cdp_active_tab(tab_id)
    if err: return err
    
    try:
        typed = await tab.type_text(selector, text)
        return _cors_json_response({
            "ok": True,
            "typed": typed,
            "selector": selector,
            "tab_id": tab.target_id,
        })
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# ---- CDP Tab Management ----

async def handle_v1_cdp_tabs(request):
    """GET /v1/browser/cdp/tabs — List all tracked tabs."""
    r = require_auth(request)
    if r: return r
    _record_request()
    
    if not _cdp_state["connected"] or not _cdp_state["manager"]:
        return _cors_json_response({"ok": True, "tabs": [], "tab_count": 0})
    
    mgr = _cdp_state["manager"]
    tabs = mgr.list_tabs()
    
    return _cors_json_response({
        "ok": True,
        "tabs": [tab.to_dict() for tab in tabs],
        "tab_count": len(tabs),
        "active_tab_id": mgr.active_tab_id,
    })


async def handle_v1_cdp_tabs_new(request):
    """POST /v1/browser/cdp/tabs/new — Open new tab.
    
    Body JSON:
        url: string (default: "about:blank")
        activate: bool (default: true)
    """
    r = require_auth(request)
    if r: return r
    _record_request()
    
    if not _cdp_state["connected"] or not _cdp_state["manager"]:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "CDP not connected"}, status=400)
    
    url = "about:blank"
    activate = True
    try:
        body = await request.json()
        url = body.get("url", "about:blank")
        activate = body.get("activate", True)
    except Exception:
        pass
    
    mgr = _cdp_state["manager"]
    
    try:
        tab = await mgr.new_tab(url, activate=activate)
        return _cors_json_response({
            "ok": True,
            "tab": tab.to_dict(),
            "tab_id": tab.target_id,
        })
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_cdp_tabs_close(request):
    """POST /v1/browser/cdp/tabs/close — Close a tab.
    
    Body JSON:
        tab_id: string (required)
    """
    r = require_auth(request)
    if r: return r
    _record_request()
    
    if not _cdp_state["connected"] or not _cdp_state["manager"]:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "CDP not connected"}, status=400)
    
    try:
        body = await request.json()
    except Exception:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)
    
    tab_id = body.get("tab_id")
    if not tab_id:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing 'tab_id'"}, status=400)
    
    mgr = _cdp_state["manager"]
    
    try:
        success = await mgr.close_tab(tab_id)
        return _cors_json_response({
            "ok": success,
            "tab_id": tab_id,
            "remaining_tabs": mgr.tab_count,
        })
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_cdp_tabs_activate(request):
    """POST /v1/browser/cdp/tabs/activate — Activate a tab.
    
    Body JSON:
        tab_id: string (required)
    """
    r = require_auth(request)
    if r: return r
    _record_request()
    
    if not _cdp_state["connected"] or not _cdp_state["manager"]:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "CDP not connected"}, status=400)
    
    try:
        body = await request.json()
    except Exception:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)
    
    tab_id = body.get("tab_id")
    if not tab_id:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing 'tab_id'"}, status=400)
    
    mgr = _cdp_state["manager"]
    
    success = mgr.activate(tab_id)
    return _cors_json_response({
        "ok": success,
        "tab_id": tab_id,
        "active_tab_id": mgr.active_tab_id,
    })


# ---- CDP Cookie Management ----

async def _ensure_cookie_manager():
    """Lazily create and start a CDPCookieManager.
    
    Tries the active tab first, then falls back to any connected tab.
    If no tab is connected, attempts to connect the first available tab.
    """
    if _cdp_state.get("cookie_mgr") and _cdp_state["cookie_mgr"].active:
        return _cdp_state["cookie_mgr"]
    
    cdp = _get_cdp_module()
    if not cdp:
        return None
    
    # Get the CDPBrowser instance from active tab
    tab, _ = await _cdp_active_tab()
    
    # If active tab is not connected, try to find any connected tab
    if not tab or not tab._browser:
        mgr = _cdp_state.get("manager")
        if mgr:
            for t in mgr.list_tabs():
                if t.connected and t._browser:
                    tab = t
                    break
            
            # If still no connected tab, try connecting the first available one
            if not tab:
                for t in mgr.list_tabs():
                    if t.ws_url:
                        try:
                            await t.connect()
                            tab = t
                            break
                        except Exception:
                            continue
    
    if not tab or not tab._browser:
        return None
    
    try:
        mgr = cdp.CDPCookieManager(tab._browser)
        await mgr.start()
        _cdp_state["cookie_mgr"] = mgr
        return mgr
    except Exception:
        return None


async def handle_v1_cdp_cookies_get(request):
    """GET /v1/browser/cdp/cookies — Get cookies.
    
    Query params:
        url: string (optional, filter by URL)
        domain: string (optional, filter by domain)
    """
    r = require_auth(request)
    if r: return r
    _record_request()
    
    if not _cdp_state["connected"]:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "CDP not connected"}, status=400)
    
    try:
        cookie_mgr = await _ensure_cookie_manager()
        if not cookie_mgr:
            _record_request(is_error=True, count_request=False)
            return _cors_json_response({"ok": False, "error": "Failed to start cookie manager"}, status=500)
        
        qs = parse_qs(request.query_string)
        url = qs.get("url", [None])[0]
        domain = qs.get("domain", [None])[0]
        
        if url:
            cookies = await cookie_mgr.get_cookies_for_url(url)
        elif domain:
            all_cookies = await cookie_mgr.get_all_cookies()
            cookies = [c for c in all_cookies if domain in c.get("domain", "")]
        else:
            cookies = await cookie_mgr.get_all_cookies()
        
        return _cors_json_response({
            "ok": True,
            "cookies": cookies,
            "count": len(cookies),
        })
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_cdp_cookies_set(request):
    """POST /v1/browser/cdp/cookies — Set a cookie.
    
    Body JSON:
        name: string (required)
        value: string (required)
        domain: string (optional)
        path: string (default: "/")
        secure: bool (default: false)
        http_only: bool (default: false)
        same_site: string (optional: "Strict"|"Lax"|"None")
        expires: float (optional, UTC timestamp)
    """
    r = require_auth(request)
    if r: return r
    _record_request()
    
    if not _cdp_state["connected"]:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "CDP not connected"}, status=400)
    
    try:
        body = await request.json()
    except Exception:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)
    
    name = body.get("name")
    value = body.get("value")
    if not name or value is None:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing 'name' or 'value'"}, status=400)
    
    try:
        cookie_mgr = await _ensure_cookie_manager()
        if not cookie_mgr:
            _record_request(is_error=True, count_request=False)
            return _cors_json_response({"ok": False, "error": "Failed to start cookie manager"}, status=500)
        
        success = await cookie_mgr.set_cookie(
            name=name,
            value=value,
            domain=body.get("domain", ""),
            path=body.get("path", "/"),
            secure=body.get("secure", False),
            http_only=body.get("http_only", False),
            same_site=body.get("same_site", ""),
            expires=body.get("expires"),
        )
        
        return _cors_json_response({
            "ok": success,
            "name": name,
            "domain": body.get("domain", ""),
        })
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_cdp_cookies_delete(request):
    """DELETE /v1/browser/cdp/cookies — Delete a cookie.
    
    Body JSON:
        name: string (required)
        domain: string (optional)
    """
    r = require_auth(request)
    if r: return r
    _record_request()
    
    if not _cdp_state["connected"]:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "CDP not connected"}, status=400)
    
    try:
        body = await request.json()
    except Exception:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)
    
    name = body.get("name")
    if not name:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing 'name'"}, status=400)
    
    try:
        cookie_mgr = await _ensure_cookie_manager()
        if not cookie_mgr:
            _record_request(is_error=True, count_request=False)
            return _cors_json_response({"ok": False, "error": "Failed to start cookie manager"}, status=500)
        
        await cookie_mgr.delete_cookie(name, domain=body.get("domain", ""))
        
        return _cors_json_response({
            "ok": True,
            "deleted": name,
        })
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_cdp_cookies_clear(request):
    """POST /v1/browser/cdp/cookies/clear — Clear all cookies."""
    r = require_auth(request)
    if r: return r
    _record_request()
    
    if not _cdp_state["connected"]:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "CDP not connected"}, status=400)
    
    try:
        cookie_mgr = await _ensure_cookie_manager()
        if not cookie_mgr:
            _record_request(is_error=True, count_request=False)
            return _cors_json_response({"ok": False, "error": "Failed to start cookie manager"}, status=500)
        
        await cookie_mgr.clear_cookies()
        
        return _cors_json_response({"ok": True, "message": "All cookies cleared"})
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_cdp_cookies_profiles(request):
    """GET /v1/browser/cdp/cookies/profiles — List cookie profiles.
    POST /v1/browser/cdp/cookies/profiles — Save/restore/delete profile.
    
    POST Body JSON:
        action: "save" | "restore" | "delete" (required)
        name: string (required)
        domain: string (optional, for save filter)
        clear_first: bool (default: true, for restore)
    """
    r = require_auth(request)
    if r: return r
    _record_request()
    
    if not _cdp_state["connected"]:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "CDP not connected"}, status=400)
    
    if request.method == "GET":
        cookie_mgr = _cdp_state.get("cookie_mgr")
        profiles = cookie_mgr.list_profiles() if cookie_mgr else []
        profile_info = []
        for name in profiles:
            info = cookie_mgr.get_profile_info(name) if cookie_mgr else None
            profile_info.append(info or {"name": name})
        
        return _cors_json_response({
            "ok": True,
            "profiles": profile_info,
            "count": len(profile_info),
        })
    
    # POST — save/restore/delete
    try:
        body = await request.json()
    except Exception:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)
    
    action = body.get("action")
    name = body.get("name")
    if not action or not name:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing 'action' or 'name'"}, status=400)
    
    try:
        cookie_mgr = await _ensure_cookie_manager()
        if not cookie_mgr:
            _record_request(is_error=True, count_request=False)
            return _cors_json_response({"ok": False, "error": "Failed to start cookie manager"}, status=500)
        
        if action == "save":
            count = await cookie_mgr.save_profile(name, domain_filter=body.get("domain"))
            return _cors_json_response({
                "ok": True,
                "action": "save",
                "profile": name,
                "cookie_count": count,
            })
        elif action == "restore":
            count = await cookie_mgr.restore_profile(
                name, 
                clear_first=body.get("clear_first", True)
            )
            return _cors_json_response({
                "ok": True,
                "action": "restore",
                "profile": name,
                "restored_count": count,
            })
        elif action == "delete":
            deleted = cookie_mgr.delete_profile(name)
            return _cors_json_response({
                "ok": deleted,
                "action": "delete",
                "profile": name,
            })
        else:
            return _cors_json_response(
                {"ok": False, "error": f"Unknown action '{action}'. Use save, restore, or delete."},
                status=400
            )
    except KeyError as e:
        return _cors_json_response({"ok": False, "error": str(e)}, status=404)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# ---- CDP Network Monitoring ----

async def handle_v1_cdp_network_start(request):
    """POST /v1/browser/cdp/network/start — Start network monitoring."""
    r = require_auth(request)
    if r: return r
    _record_request()
    
    if not _cdp_state["connected"]:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "CDP not connected"}, status=400)
    
    cdp = _get_cdp_module()
    if not cdp:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "cdp_browser module not found"}, status=500)
    
    try:
        # Get browser from active tab
        tab, _ = await _cdp_active_tab()
        if not tab or not tab._browser:
            _record_request(is_error=True, count_request=False)
            return _cors_json_response({"ok": False, "error": "No active tab with CDP connection"}, status=400)
        
        if _cdp_state.get("monitor") and _cdp_state["monitor"].active:
            return _cors_json_response({"ok": True, "message": "Network monitoring already active"})
        
        max_entries = 1000
        try:
            body = await request.json()
            max_entries = body.get("max_entries", 1000)
        except Exception:
            pass
        
        monitor = cdp.CDPNetworkMonitor(tab._browser, max_entries=max_entries)
        await monitor.start()
        _cdp_state["monitor"] = monitor
        
        return _cors_json_response({
            "ok": True,
            "message": "Network monitoring started",
            "max_entries": max_entries,
        })
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_cdp_network_stop(request):
    """POST /v1/browser/cdp/network/stop — Stop network monitoring."""
    r = require_auth(request)
    if r: return r
    _record_request()
    
    monitor = _cdp_state.get("monitor")
    if not monitor or not monitor.active:
        return _cors_json_response({"ok": True, "message": "Network monitoring not active"})
    
    try:
        await monitor.stop()
        return _cors_json_response({"ok": True, "message": "Network monitoring stopped"})
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_cdp_network_requests(request):
    """GET /v1/browser/cdp/network/requests — Get captured network requests.
    
    Query params:
        url_filter: string (optional)
        resource_type: string (optional)
        include_active: bool (default: true)
    """
    r = require_auth(request)
    if r: return r
    _record_request()
    
    monitor = _cdp_state.get("monitor")
    if not monitor:
        return _cors_json_response({"ok": True, "requests": [], "count": 0, "active_count": 0})
    
    qs = parse_qs(request.query_string)
    url_filter = qs.get("url_filter", [None])[0]
    resource_type = qs.get("resource_type", [None])[0]
    include_active = qs.get("include_active", ["true"])[0].lower() == "true"
    
    try:
        finished = monitor.get_requests(url_filter=url_filter, resource_type=resource_type)
        requests_list = [req.to_dict() for req in finished]
        
        result = {
            "ok": True,
            "requests": requests_list,
            "total_finished": monitor.total_requests,
            "active_count": monitor.active_count,
        }
        
        if include_active:
            active = monitor.get_active_requests()
            result["active"] = [req.to_dict() for req in active]
        
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_cdp_network_har(request):
    """GET /v1/browser/cdp/network/har — Export captured requests as HAR."""
    r = require_auth(request)
    if r: return r
    _record_request()
    
    monitor = _cdp_state.get("monitor")
    if not monitor:
        return _cors_json_response({"log": {"version": "1.2", "creator": {"name": "arena-cdp", "version": "1.0"}, "entries": []}})
    
    try:
        har = monitor.export_har()
        return _cors_json_response(har)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# ---- CDP Network Interception ----

async def handle_v1_cdp_intercept_start(request):
    """POST /v1/browser/cdp/intercept/start — Start network interception.
    
    Body JSON (optional):
        patterns: list of Fetch pattern dicts (default: intercept all)
    """
    r = require_auth(request)
    if r: return r
    _record_request()
    
    if not _cdp_state["connected"]:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "CDP not connected"}, status=400)
    
    cdp = _get_cdp_module()
    if not cdp:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "cdp_browser module not found"}, status=500)
    
    try:
        tab, _ = await _cdp_active_tab()
        if not tab or not tab._browser:
            _record_request(is_error=True, count_request=False)
            return _cors_json_response({"ok": False, "error": "No active tab"}, status=400)
        
        if _cdp_state.get("interceptor") and _cdp_state["interceptor"].active:
            return _cors_json_response({"ok": True, "message": "Interception already active"})
        
        patterns = None
        try:
            body = await request.json()
            patterns = body.get("patterns")
        except Exception:
            pass
        
        interceptor = cdp.CDPNetworkInterceptor(tab._browser)
        await interceptor.start(patterns=patterns)
        _cdp_state["interceptor"] = interceptor
        
        return _cors_json_response({
            "ok": True,
            "message": "Network interception started",
        })
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_cdp_intercept_stop(request):
    """POST /v1/browser/cdp/intercept/stop — Stop network interception."""
    r = require_auth(request)
    if r: return r
    _record_request()
    
    interceptor = _cdp_state.get("interceptor")
    if not interceptor or not interceptor.active:
        return _cors_json_response({"ok": True, "message": "Interception not active"})
    
    try:
        await interceptor.stop()
        return _cors_json_response({"ok": True, "message": "Interception stopped"})
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_cdp_intercept_rule(request):
    """POST /v1/browser/cdp/intercept/rule — Add interception rule.
    DELETE /v1/browser/cdp/intercept/rule — Remove interception rule.
    GET /v1/browser/cdp/intercept/rules — List interception rules.
    
    POST Body JSON:
        name: string (required)
        url_pattern: string (optional)
        resource_type: string (optional)
        action: "block" | "redirect" | "modify_headers" | "mock" (required)
        redirect_url: string (for action="redirect")
        mock_status: int (for action="mock", default: 200)
        mock_body: string (for action="mock")
        mock_content_type: string (for action="mock", default: "text/plain")
    
    DELETE Body JSON:
        name: string (required)
    """
    r = require_auth(request)
    if r: return r
    _record_request()
    
    cdp = _get_cdp_module()
    if not cdp:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "cdp_browser module not found"}, status=500)
    
    interceptor = _cdp_state.get("interceptor")
    
    if request.method == "GET":
        if not interceptor:
            return _cors_json_response({"ok": True, "rules": [], "count": 0})
        rules = interceptor.get_rules()
        return _cors_json_response({
            "ok": True,
            "rules": [rule.to_dict() for rule in rules],
            "count": len(rules),
        })
    
    try:
        body = await request.json()
    except Exception:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)
    
    if request.method == "DELETE":
        name = body.get("name")
        if not name:
            _record_request(is_error=True, count_request=False)
            return _cors_json_response({"ok": False, "error": "missing 'name'"}, status=400)
        
        if not interceptor:
            _record_request(is_error=True, count_request=False)
            return _cors_json_response({"ok": False, "error": "No active interceptor"}, status=400)
        
        removed = interceptor.remove_rule(name)
        return _cors_json_response({
            "ok": removed,
            "name": name,
        })
    
    # POST — add rule
    if not interceptor or not interceptor.active:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "Interception not active. Start first."}, status=400)
    
    name = body.get("name", "")
    action = body.get("action")
    if not action:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing 'action'"}, status=400)
    
    try:
        rule = cdp.InterceptRule(
            name=name,
            url_pattern=body.get("url_pattern"),
            resource_type=body.get("resource_type"),
            action=action,
            redirect_url=body.get("redirect_url"),
            mock_status=body.get("mock_status", 200),
            mock_body=body.get("mock_body"),
            mock_content_type=body.get("mock_content_type", "text/plain"),
            modify_request_headers=body.get("modify_request_headers"),
            remove_request_headers=body.get("remove_request_headers"),
        )
        interceptor.add_rule(rule)
        
        return _cors_json_response({
            "ok": True,
            "rule": rule.to_dict(),
        })
    except ValueError as e:
        return _cors_json_response({"ok": False, "error": str(e)}, status=400)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# ---- CDP Session Health Check ----

async def handle_v1_cdp_session_check(request):
    """GET /v1/browser/cdp/session/check — Check session health.
    
    Query params:
        domain: string (required)
        auth_cookie_names: string (comma-separated, optional)
    """
    r = require_auth(request)
    if r: return r
    _record_request()
    
    if not _cdp_state["connected"]:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "CDP not connected"}, status=400)
    
    qs = parse_qs(request.query_string)
    domain = qs.get("domain", [None])[0]
    if not domain:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing 'domain' parameter"}, status=400)
    
    auth_names_str = qs.get("auth_cookie_names", [None])[0]
    auth_cookie_names = auth_names_str.split(",") if auth_names_str else None
    
    try:
        cookie_mgr = await _ensure_cookie_manager()
        if not cookie_mgr:
            _record_request(is_error=True, count_request=False)
            return _cors_json_response({"ok": False, "error": "Failed to start cookie manager"}, status=500)
        
        result = await cookie_mgr.check_session(domain, auth_cookie_names)
        return _cors_json_response({"ok": True, **result})
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/recall GET — Smart memory recall with TF scoring ---

def _recall_sync(query: str, top: int) -> dict:
    """Recall relevant facts using term frequency scoring."""
    facts = _load_facts()
    if not facts:
        return {"ok": True, "query": query, "count": 0, "facts": []}

    # Tokenize query
    query_terms = set(re.findall(r'\w+', query.lower()))
    if not query_terms:
        # Return most recent if no meaningful terms
        return {"ok": True, "query": query, "count": min(top, len(facts)),
                "facts": [{"fact": f, "score": 0.0} for f in facts[-top:]]}

    scored = []
    for fact in facts:
        fact_text = json.dumps(fact, ensure_ascii=False).lower()
        fact_terms = re.findall(r'\w+', fact_text)
        if not fact_terms:
            scored.append({"fact": fact, "score": 0.0})
            continue

        # TF scoring: count how many query terms appear in the fact
        term_counts = collections.Counter(fact_terms)
        score = 0.0
        for qt in query_terms:
            if qt in term_counts:
                # TF score: frequency of matching term / total terms
                score += term_counts[qt] / len(fact_terms)
        scored.append({"fact": fact, "score": round(score, 6)})

    # Sort by score descending, then by recency (position in list)
    scored.sort(key=lambda x: x["score"], reverse=True)

    # Filter out zero-score if we have enough scored results
    non_zero = [s for s in scored if s["score"] > 0]
    if non_zero:
        result_facts = non_zero[:top]
    else:
        result_facts = scored[:top]

    return {"ok": True, "query": query, "count": len(result_facts), "facts": result_facts}


async def handle_v1_recall(request: web.Request) -> web.Response:
    """GET /v1/recall?q=query&top=5 — Smart memory recall with TF scoring."""
    r = require_auth(request)
    if r: return r
    _record_request()
    qs = parse_qs(request.query_string)
    query = qs.get("q", [""])[0]
    top = int(qs.get("top", ["5"])[0])
    if not query:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing q parameter"}, status=400)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _recall_sync, query, top)
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/recall/digest GET — Memory digest ---

def _recall_digest_sync() -> dict:
    """Compact markdown digest of recent memory (facts + recent audit events)."""
    lines: list[str] = []
    lines.append("# Memory Digest")
    lines.append(f"Generated: {utc_now()}\n")

    # Load recent facts (last 50)
    facts = _load_facts()
    recent_facts = facts[-50:]
    lines.append(f"## Recent Facts ({len(recent_facts)} of {len(facts)})\n")
    for f in recent_facts:
        key = f.get("key", "unknown")
        value = str(f.get("value", ""))[:200]
        ts = f.get("timestamp", "")
        tags = f.get("tags", [])
        tag_str = f" [{', '.join(tags)}]" if tags else ""
        lines.append(f"- **{key}**{tag_str}: {value} _({ts})_")
    lines.append("")

    # Load recent audit events (last 20)
    audit_lines = read_tail(AUDIT, 20)
    events = []
    for line in audit_lines:
        try:
            events.append(json.loads(line))
        except Exception:
            pass

    lines.append(f"## Recent Audit Events ({len(events)})\n")
    for ev in events:
        ev_type = ev.get("type", "unknown")
        ts = ev.get("ts", "")
        detail = ""
        if "cmd" in ev:
            detail = f": `{ev['cmd'][:100]}`"
        elif "path" in ev:
            detail = f": {ev['path']}"
        elif "error" in ev:
            detail = f": {str(ev['error'])[:100]}"
        lines.append(f"- [{ev_type}] _{ts}_{detail}")
    lines.append("")

    digest = "\n".join(lines)
    return {"ok": True, "digest": digest, "fact_count": len(recent_facts), "event_count": len(events)}


async def handle_v1_recall_digest(request: web.Request) -> web.Response:
    """GET /v1/recall/digest — Memory digest."""
    r = require_auth(request)
    if r: return r
    _record_request()
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _recall_digest_sync)
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/audit/stats GET — Audit statistics ---

def _audit_stats_sync() -> dict:
    """Count events by type, show totals, time range."""
    if not AUDIT.exists():
        return {"ok": True, "total": 0, "by_type": {}, "first_ts": None, "last_ts": None}

    by_type: dict[str, int] = collections.Counter()
    total = 0
    first_ts: str | None = None
    last_ts: str | None = None

    with open(AUDIT, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
                total += 1
                ev_type = ev.get("type", "unknown")
                by_type[ev_type] += 1
                ts = ev.get("ts", "")
                if ts:
                    if first_ts is None:
                        first_ts = ts
                    last_ts = ts
            except json.JSONDecodeError:
                total += 1
                by_type["parse_error"] += 1

    return {"ok": True, "total": total, "by_type": dict(by_type),
            "first_ts": first_ts, "last_ts": last_ts}


async def handle_v1_audit_stats(request: web.Request) -> web.Response:
    """GET /v1/audit/stats — Audit statistics."""
    r = require_auth(request)
    if r: return r
    _record_request()
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _audit_stats_sync)
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/tasks GET — Task queue management ---

def _tasks_list_sync(status: str, limit: int) -> dict:
    """List JSON files in queue directories."""
    tasks: list[dict] = []

    # Determine which directories to scan based on status filter
    if status and status in ("inbox", "running", "done", "failed"):
        dirs = {"inbox": INBOX, "running": RUNNING, "done": DONE, "failed": FAILED}
        scan_dirs = [(status, dirs[status])]
    else:
        scan_dirs = [("inbox", INBOX), ("running", RUNNING), ("done", DONE), ("failed", FAILED)]

    for state_name, scan_dir in scan_dirs:
        if not scan_dir.exists():
            continue
        for p in sorted(scan_dir.glob("*.json"))[:limit]:
            try:
                task = json.loads(p.read_text(encoding="utf-8"))
                task["id"] = task.get("id", p.stem)
                task["state"] = state_name
                task["file"] = str(p)
                # Remove potentially large output fields
                task.pop("stdout", None)
                task.pop("stderr", None)
                tasks.append(task)
            except Exception:
                tasks.append({"id": p.stem, "state": state_name, "file": str(p), "error": "unreadable"})
            if len(tasks) >= limit:
                break

    return {"ok": True, "count": len(tasks), "tasks": tasks}


async def handle_v1_tasks_get(request: web.Request) -> web.Response:
    """GET /v1/tasks?status=inbox|running|done|failed&limit=20 — list tasks."""
    r = require_auth(request)
    if r: return r
    _record_request()
    qs = parse_qs(request.query_string)
    status = qs.get("status", [""])[0]
    limit = int(qs.get("limit", ["20"])[0])
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _tasks_list_sync, status, limit)
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/tasks POST — Submit task ---

def _task_submit_sync(data: dict) -> dict:
    """Create JSON file in INBOX."""
    task_id = str(uuid.uuid4())[:8]
    task = {
        "id": task_id,
        "cmd": data.get("cmd", ""),
        "cwd": data.get("cwd", str(Path.home())),
        "timeout": data.get("timeout", 3600),
        "env": data.get("env", {}),
        "state": "inbox",
        "created_at": utc_now(),
    }
    INBOX.mkdir(parents=True, exist_ok=True)
    task_path = INBOX / f"{task_id}.json"
    task_path.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "task_id": task_id}


async def handle_v1_tasks_post(request: web.Request) -> web.Response:
    """POST /v1/tasks — Submit task. Body: {cmd, cwd?, timeout?, env?}."""
    r = require_auth(request)
    if r: return r
    _record_request()
    try:
        data = await request.json()
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": f"invalid json: {e}"}, status=400)
    cmd = data.get("cmd", "")
    if not cmd:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing cmd"}, status=400)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _task_submit_sync, data)
        audit({"type": "task_submit", "task_id": result.get("task_id"), "cmd": cmd})
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/tasks/clean POST — Clean completed tasks ---

def _tasks_clean_sync() -> dict:
    """Remove done/failed task files older than 24h."""
    removed = 0
    cutoff = time.time() - 86400  # 24 hours ago

    for scan_dir in [DONE, FAILED]:
        if not scan_dir.exists():
            continue
        for p in scan_dir.glob("*.json"):
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink()
                    removed += 1
            except Exception:
                pass

    return {"ok": True, "removed": removed}


async def handle_v1_tasks_clean(request: web.Request) -> web.Response:
    """POST /v1/tasks/clean — Clean completed tasks older than 24h."""
    r = require_auth(request)
    if r: return r
    _record_request()
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _tasks_clean_sync)
        audit({"type": "tasks_clean", "removed": result.get("removed", 0)})
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/backups GET — List existing backups ---

def _backups_list_sync() -> dict:
    """List zip files in BACKUPS_DIR with size + mtime."""
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for p in sorted(BACKUPS_DIR.glob("*.zip"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            st = p.stat()
            items.append({
                "name": p.name,
                "size": st.st_size,
                "modified": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
                "created_at": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
            })
        except Exception:
            continue
    return {"ok": True, "count": len(items), "backups": items, "dir": str(BACKUPS_DIR)}


async def handle_v1_backups(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    _record_request()
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _backups_list_sync)
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/backup/{name} GET — Download specific backup ---

async def handle_v1_backup_download(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    _record_request()
    name = request.match_info.get("name", "")
    # Security: no path traversal
    if not name or "/" in name or "\\" in name or ".." in name:
        return _cors_json_response({"ok": False, "error": "invalid name"}, status=400)
    if not name.endswith(".zip"):
        name += ".zip"
    path = BACKUPS_DIR / name
    if not path.exists() or not path.is_file():
        return _cors_json_response({"ok": False, "error": "not found"}, status=404)
    try:
        return web.FileResponse(
            path=path,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Content-Disposition": f'attachment; filename="{name}"',
                "Content-Type": "application/zip",
            },
        )
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/backup POST — Create backup ---

def _backup_sync(paths: list[str], name: str) -> dict:
    """Create zip of specified directories."""
    SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".next", ".turbo", ".arena", "venv", "shots", "reports", "logs"}
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)

    if not name:
        name = f"backup-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    if not name.endswith(".zip"):
        name += ".zip"

    backup_path = BACKUPS_DIR / name
    file_count = 0
    start_time = time.time()
    MAX_BACKUP_TIME = 60  # 60 seconds max for backup creation

    total_size = 0
    MAX_BACKUP_SIZE = 100 * 1024 * 1024  # 100MB max backup
    with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for path_str in paths:
            # Check time limit
            if time.time() - start_time > MAX_BACKUP_TIME:
                break
            p = Path(path_str).expanduser()
            if p.is_file():
                fsize = p.stat().st_size
                if total_size + fsize > MAX_BACKUP_SIZE:
                    continue
                zf.write(p, p.name)
                total_size += fsize
                file_count += 1
            elif p.is_dir():
                for root, dirs, files in os.walk(p, topdown=True):
                    # Check time limit during walk
                    if time.time() - start_time > MAX_BACKUP_TIME:
                        break
                    dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                    for fname in files:
                        if time.time() - start_time > MAX_BACKUP_TIME:
                            break
                        fpath = Path(root) / fname
                        try:
                            fsize = fpath.stat().st_size
                            if fsize > 50 * 1024 * 1024:
                                continue
                            if total_size + fsize > MAX_BACKUP_SIZE:
                                break
                        except Exception:
                            continue
                        arcname = str(fpath.relative_to(p.parent))
                        zf.write(fpath, arcname)
                        total_size += fsize
                        file_count += 1
                        if file_count >= 500:
                            break
                    if file_count >= 500 or total_size >= MAX_BACKUP_SIZE:
                        break

    size = backup_path.stat().st_size if backup_path.exists() else 0
    return {"ok": True, "backup_path": str(backup_path), "size": size, "file_count": file_count}


async def handle_v1_backup(request: web.Request) -> web.Response:
    """POST /v1/backup — Create backup. Body: {paths?: [list], name?: string}."""
    r = require_auth(request)
    if r: return r
    _record_request()
    try:
        data = await request.json()
    except Exception:
        data = {}
    paths = data.get("paths", [str(BRIDGE_DIR)])
    name = data.get("name", "")
    # Validate backup name for path traversal
    if name and (".." in name or "/" in name or "\\" in name):
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "invalid backup name"}, status=400)
    try:
        loop = asyncio.get_event_loop()
        # Use dedicated slow executor with timeout to avoid blocking main pool
        result = await asyncio.wait_for(
            loop.run_in_executor(_SLOW_EXECUTOR, _backup_sync, paths, name),
            timeout=120.0
        )
        audit({"type": "backup", "name": name, "paths": paths, "size": result.get("size", 0),
               "file_count": result.get("file_count", 0)})
        return _cors_json_response(result)
    except asyncio.TimeoutError:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "Backup timed out (120s) — directory may be too large"}, status=504)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/skills GET — List skills ---

def _skills_list_sync() -> dict:
    """Scan arena-bridge/skills/ directory for skill definitions."""
    skills: list[dict] = []
    if not SKILLS_DIR.exists():
        return {"ok": True, "count": 0, "skills": []}

    for p in sorted(SKILLS_DIR.rglob("*")):
        if p.is_file() and p.suffix in (".json", ".yaml", ".yml", ".md", ".toml"):
            rel = p.relative_to(SKILLS_DIR)
            skill_info: dict[str, Any] = {
                "name": str(rel.with_suffix("")),
                "file": str(rel),
                "ext": p.suffix,
                "size": p.stat().st_size,
            }
            # Try to parse JSON skill definitions
            if p.suffix == ".json":
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    skill_info["description"] = data.get("description", "")
                    skill_info["version"] = data.get("version", "")
                except Exception:
                    pass
            skills.append(skill_info)

    return {"ok": True, "count": len(skills), "skills": skills}


async def handle_v1_skills(request: web.Request) -> web.Response:
    """GET /v1/skills — List skills."""
    r = require_auth(request)
    if r: return r
    _record_request()
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _skills_list_sync)
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/skills/run POST — Run a skill ---

def _skills_run_sync(name: str, args: list[str], env_extra: dict | None = None) -> dict:
    """Execute a skill via agentctl or directly.

    Supports three skill types:
    1. Executable skills: have run.sh or run.py — executed as subprocess
    2. Prompt-only skills: have SKILL.md but no runner — return SKILL.md content
    3. Fallback: try agentctl skill run
    """
    # Try direct skill runner first (faster, supports JSON input via env)
    skill_dir = SKILLS_DIR / name
    if not skill_dir.exists() and SKILLS_DIR.exists():
        # Try flat name under skills/ (e.g. "browseract" -> skills/browseract/)
        for d in SKILLS_DIR.iterdir():
            if d.is_dir() and d.name == name:
                skill_dir = d
                break
        else:
            # Recursive search: "hello" could be at skills/sandbox/hello/
            # Also find prompt-only skills (SKILL.md without runner)
            for d in SKILLS_DIR.rglob(name):
                if d.is_dir() and (
                    (d / "run.sh").exists() or (d / "run.py").exists() or (d / "SKILL.md").exists()
                ):
                    skill_dir = d
                    break

    runner_sh = skill_dir / "run.sh"
    runner_py = skill_dir / "run.py"
    skill_md = skill_dir / "SKILL.md"

    # --- Executable skills (run.sh / run.py) ---
    if skill_dir.exists() and (runner_sh.exists() or runner_py.exists()):
        # Direct execution — faster, passes input via env vars
        env = os.environ.copy()
        env["ARENA_AGENT_HOME"] = str(ROOT_AGENT)
        env["SKILL_NAME"] = name
        env["SKILL_DIR"] = str(skill_dir)
        env["SKILL_ARGS"] = json.dumps(args)
        if env_extra:
            for k, v in env_extra.items():
                env[k] = str(v) if not isinstance(v, str) else v

        if runner_sh.exists():
            # Use bash to execute .sh files (git may not preserve +x bit)
            cmd = ["bash", str(runner_sh)] + list(args)
        else:
            py = sys.executable or "python3"
            cmd = [py, str(runner_py)] + list(args)

        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                               env=env, **_subprocess_kwargs())
            return {"ok": p.returncode == 0, "exit_code": p.returncode,
                    "stdout": p.stdout[-15000:], "stderr": p.stderr[-3000:]}
        except subprocess.TimeoutExpired:
            return {"ok": False, "exit_code": -1, "stdout": "", "stderr": "timeout"}
        except Exception as e:
            return {"ok": False, "exit_code": -2, "stdout": "", "stderr": str(e)}

    # --- Prompt-only skills (SKILL.md without runner) ---
    # These are instruction/prompt skills (e.g., SuperPowers) — return SKILL.md content
    if skill_dir.exists() and skill_md.exists() and not runner_sh.exists() and not runner_py.exists():
        try:
            content = skill_md.read_text(encoding="utf-8")
            return {
                "ok": True,
                "exit_code": 0,
                "output": content,
                "skill_type": "prompt",
                "skill_name": name,
                "skill_dir": str(skill_dir),
                "stdout": content[:500] + ("..." if len(content) > 500 else ""),
                "stderr": "",
            }
        except Exception as e:
            return {"ok": False, "exit_code": -2, "stdout": "", "stderr": f"Failed to read SKILL.md: {e}"}

    # Fallback: agentctl skill run
    cmd_args = [os.path.join(BIN, "agentctl"), "skill", "run", name] + list(args)
    try:
        p = subprocess.run(cmd_args, capture_output=True, text=True, timeout=300, **_subprocess_kwargs())
        return {"ok": p.returncode == 0, "exit_code": p.returncode,
                "stdout": p.stdout[-15000:], "stderr": p.stderr[-3000:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "exit_code": -1, "stdout": "", "stderr": "timeout"}
    except Exception as e:
        return {"ok": False, "exit_code": -2, "stdout": "", "stderr": str(e)}


async def handle_v1_skills_run(request: web.Request) -> web.Response:
    """POST /v1/skills/run — Run a skill. Body: {name, args?: [], input?: {}}.

    - `name`: skill name (e.g. "browseract", "core/health", "web/research")
    - `args`: positional args passed to run.sh/run.py (e.g. ["open", "https://example.com"])
    - `input`: JSON object passed as SKILL_INPUT env var for skills that accept structured input
    """
    r = require_auth(request)
    if r: return r
    _record_request()
    try:
        data = await request.json()
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": f"invalid json: {e}"}, status=400)
    name = data.get("name", "")
    if not name:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing name"}, status=400)
    skill_args = data.get("args") or []
    skill_input = data.get("input") or {}

    # If input is provided but args are not, derive args from input
    if skill_input and not skill_args:
        # Common patterns: extract url, query, action as positional args
        if "action" in skill_input and "url" in skill_input:
            # BrowserAct-style: {action: "open", url: "..."}
            skill_args = [skill_input["action"], skill_input["url"]]
        elif "url" in skill_input and "task" in skill_input:
            # BrowserAct extract: {url: "...", task: "..."}
            skill_args = ["extract", skill_input["url"], "--task", skill_input["task"]]
        elif "url" in skill_input:
            # Simple URL: {url: "..."}
            skill_args = ["open", skill_input["url"]]
        elif "query" in skill_input:
            # Search/research: {query: "...", n?: 3}
            skill_args = [skill_input["query"]]
            if "n" in skill_input:
                skill_args.append(str(skill_input["n"]))

    # Build env extras from input
    env_extra = {}
    if skill_input:
        env_extra["SKILL_INPUT"] = json.dumps(skill_input)

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _skills_run_sync, name, skill_args, env_extra)
        audit({"type": "skill_run", "name": name, "args": skill_args, "ok": result.get("ok", False)})
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/hooks GET — List hooks ---

def _hooks_list_sync() -> dict:
    """Read hooks from arena-bridge/hooks/."""
    hooks: list[dict] = []
    if not HOOKS_DIR.exists():
        return {"ok": True, "count": 0, "hooks": []}

    for p in sorted(HOOKS_DIR.iterdir()):
        if p.is_file() and p.suffix in (".json", ".yaml", ".yml", ".toml"):
            hook_info: dict[str, Any] = {
                "name": p.stem,
                "file": p.name,
                "ext": p.suffix,
                "size": p.stat().st_size,
            }
            if p.suffix == ".json":
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    hook_info["event"] = data.get("event", "")
                    hook_info["description"] = data.get("description", "")
                except Exception:
                    pass
            hooks.append(hook_info)

    return {"ok": True, "count": len(hooks), "hooks": hooks}


async def handle_v1_hooks(request: web.Request) -> web.Response:
    """GET /v1/hooks — List hooks."""
    r = require_auth(request)
    if r: return r
    _record_request()
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _hooks_list_sync)
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/agents GET — List agent configs ---

def _agents_list_sync() -> dict:
    """Scan arena-bridge/agents/ for agent config files."""
    agents: list[dict] = []
    if not AGENTS_DIR.exists():
        return {"ok": True, "count": 0, "agents": []}

    for p in sorted(AGENTS_DIR.iterdir()):
        if p.is_file() and p.suffix in (".json", ".yaml", ".yml", ".toml", ".md"):
            agent_info: dict[str, Any] = {
                "name": p.stem,
                "file": p.name,
                "ext": p.suffix,
                "size": p.stat().st_size,
            }
            if p.suffix == ".json":
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    agent_info["description"] = data.get("description", "")
                    agent_info["model"] = data.get("model", "")
                except Exception:
                    pass
            agents.append(agent_info)
        elif p.is_dir():
            agents.append({"name": p.name, "file": f"{p.name}/", "ext": "[dir]",
                           "size": len(list(p.iterdir()))})

    return {"ok": True, "count": len(agents), "agents": agents}


async def handle_v1_agents(request: web.Request) -> web.Response:
    """GET /v1/agents — List agent configs."""
    r = require_auth(request)
    if r: return r
    _record_request()
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _agents_list_sync)
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/subagents GET — List subagents ---

def _subagents_list_sync() -> dict:
    """Read from arena-bridge/subagents/."""
    subagents: list[dict] = []
    if not SUBAGENTS_DIR.exists():
        return {"ok": True, "count": 0, "subagents": []}

    for p in sorted(SUBAGENTS_DIR.iterdir()):
        if p.is_file():
            sa_info: dict[str, Any] = {
                "name": p.stem,
                "file": p.name,
                "ext": p.suffix,
                "size": p.stat().st_size,
                "modified": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(),
            }
            if p.suffix == ".json":
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    sa_info["status"] = data.get("status", "")
                    sa_info["cmd"] = data.get("cmd", "")[:200]
                except Exception:
                    pass
            subagents.append(sa_info)

    return {"ok": True, "count": len(subagents), "subagents": subagents}


async def handle_v1_subagents(request: web.Request) -> web.Response:
    """GET /v1/subagents — List subagents."""
    r = require_auth(request)
    if r: return r
    _record_request()
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _subagents_list_sync)
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/subagents/spawn POST — Spawn subagent ---

def _subagents_spawn_sync(data: dict) -> dict:
    """Spawn a subagent."""
    cmd = data.get("cmd", "")
    name = data.get("name", "")
    wait = data.get("wait", True)
    timeout = data.get("timeout", 300)

    cmd_args = [sys.executable, os.path.join(BIN, "subagent.py"), "spawn", cmd]
    if name:
        cmd_args += ["--name", name]
    if wait:
        cmd_args += ["--wait"]
    cmd_args += ["--timeout", str(timeout)]

    try:
        p = subprocess.run(cmd_args, capture_output=True, text=True, timeout=timeout + 30, **_subprocess_kwargs())
        return {"ok": p.returncode == 0, "exit_code": p.returncode,
                "stdout": p.stdout[-10000:], "stderr": p.stderr[-3000:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "exit_code": -1, "stdout": "", "stderr": "timeout"}
    except Exception as e:
        return {"ok": False, "exit_code": -2, "stdout": "", "stderr": str(e)}


async def handle_v1_subagents_spawn(request: web.Request) -> web.Response:
    """POST /v1/subagents/spawn — Spawn subagent. Body: {cmd, name?, wait?, timeout?}."""
    r = require_auth(request)
    if r: return r
    _record_request()
    try:
        data = await request.json()
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": f"invalid json: {e}"}, status=400)
    cmd = data.get("cmd", "")
    if not cmd:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing cmd"}, status=400)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _subagents_spawn_sync, data)
        audit({"type": "subagent_spawn", "cmd": cmd, "name": data.get("name", ""),
               "ok": result.get("ok", False)})
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/mission/show GET — Show mission details ---

def _mission_show_sync(name: str) -> dict:
    """Read and return mission file content."""
    if ".." in name or "/" in name or "\\" in name or name.startswith("."):
        return {"ok": False, "error": "invalid mission name"}
    # Try various extensions
    for ext in ("", ".json", ".yaml", ".yml", ".md", ".txt"):
        p = MISSIONS_DIR / f"{name}{ext}"
        if p.exists() and p.is_file():
            content = p.read_text(encoding="utf-8", errors="replace")
            return {"ok": True, "name": name, "file": str(p), "ext": p.suffix or ext,
                    "content": content, "size": p.stat().st_size}

    # Check if it's a directory
    d = MISSIONS_DIR / name
    if d.exists() and d.is_dir():
        files = []
        for f in sorted(d.iterdir()):
            files.append({"name": f.name, "size": f.stat().st_size if f.is_file() else 0,
                          "is_dir": f.is_dir()})
        return {"ok": True, "name": name, "is_dir": True, "files": files}

    return {"ok": False, "error": f"mission '{name}' not found"}


async def handle_v1_mission_show(request: web.Request) -> web.Response:
    """GET /v1/mission/show?name=mission_name — Show mission details."""
    r = require_auth(request)
    if r: return r
    _record_request()
    qs = parse_qs(request.query_string)
    name = qs.get("name", [""])[0]
    if not name:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing name parameter"}, status=400)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _mission_show_sync, name)
        if not result.get("ok"):
            _record_request(is_error=True, count_request=False)
            return _cors_json_response(result, status=404)
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/metrics GET — Bridge performance metrics ---

async def handle_v1_metrics(request: web.Request) -> web.Response:
    """GET /v1/metrics — Bridge performance metrics."""
    try:
        _record_request()
        with _metrics_lock:
            durations = BRIDGE_METRICS["request_durations"]
            avg_duration = round(sum(durations) / len(durations), 6) if durations else 0.0
            uptime = round(time.time() - BRIDGE_METRICS["start_time"], 1)
            error_rate = 0.0
            if BRIDGE_METRICS["total_requests"] > 0:
                error_rate = round(BRIDGE_METRICS["total_errors"] / BRIDGE_METRICS["total_requests"] * 100, 2)

            result = {
                "ok": True,
                "uptime_seconds": uptime,
                "total_requests": BRIDGE_METRICS["total_requests"],
                "total_exec": BRIDGE_METRICS["total_exec"],
                "total_errors": BRIDGE_METRICS["total_errors"],
                "average_duration_sec": avg_duration,
                "error_rate_percent": error_rate,
                "start_time": datetime.fromtimestamp(BRIDGE_METRICS["start_time"], tz=timezone.utc).isoformat(),
                "version": VERSION,
                "active_processes": len(ACTIVE_PROCESSES),
            }
        return _cors_json_response(result)


    # ============================================================================
    # HANDLERS — MCP Streamable HTTP
    # ============================================================================
    except Exception as e:
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)

async def handle_mcp_post(request: web.Request) -> web.Response:
    """MCP Streamable HTTP — main endpoint."""
    r = require_auth(request)
    if r: return r
    _record_request()
    try:
        msg = await request.json()
    except Exception:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}}, status=400)

    # New session on initialize
    session_hdr = request.headers.get("Mcp-Session-Id", "")
    if msg.get("method") == "initialize":
        session = sid()
        request.app["mcp_sessions"][session] = {"created": now_ms()}
        resp = handle_rpc(msg)
        return web.json_response(resp, headers={
            "Mcp-Session-Id": session,
            "Access-Control-Allow-Origin": "*",
        })

    resp = handle_rpc(msg)
    if resp is None:
        return web.Response(status=204, headers={"Access-Control-Allow-Origin": "*"})
    return web.json_response(resp, headers={"Access-Control-Allow-Origin": "*"})


async def handle_mcp_delete(request: web.Request) -> web.Response:
    """Close MCP session."""
    try:
        sess = request.headers.get("Mcp-Session-Id", "")
        request.app["mcp_sessions"].pop(sess, None)
        return web.Response(status=204, headers={"Access-Control-Allow-Origin": "*"})


    # ============================================================================
    # HANDLERS — MCP SSE Legacy
    # ============================================================================
    except Exception as e:
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)

async def handle_sse(request: web.Request) -> web.Response:
    """SSE legacy transport — open event stream."""
    r = require_auth(request)
    if r: return r
    _record_request()
    session = sid()
    request.app["mcp_sessions"][session] = {"created": now_ms()}

    resp = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": request.headers.get("Origin", "*"),
            "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Mcp-Session-Id, Last-Event-ID, Authorization",
            "Access-Control-Expose-Headers": "Mcp-Session-Id",
        }
    )
    await resp.prepare(request)
    await resp.write(f"event: endpoint\ndata: /messages?session_id={session}\n\n".encode())

    # Keep alive with periodic pings
    try:
        while True:
            await asyncio.sleep(15)
            await resp.write(b": keepalive\n\n")
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    finally:
        request.app["mcp_sessions"].pop(session, None)

    return resp


async def handle_sse_messages(request: web.Request) -> web.Response:
    """SSE legacy peer message endpoint."""
    r = require_auth(request)
    if r: return r
    _record_request()
    try:
        msg = await request.json()
    except Exception:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}}, status=400)

    # Process the RPC message
    handle_rpc(msg)
    return web.Response(status=202, headers={"Access-Control-Allow-Origin": "*"})


# ============================================================================
# HANDLER — MCP WebSocket
# ============================================================================

async def handle_ws(request: web.Request) -> web.WebSocketResponse:
    """WebSocket MCP transport — full-duplex JSON-RPC."""
    r = require_auth(request)
    if r:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_json({"jsonrpc": "2.0", "error": {"code": -32001, "message": "unauthorized"}})
        await ws.close()
        return ws
    _record_request()
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    async for msg in ws:
        if msg.type == aiohttp.WSMsgType.TEXT:
            try:
                data = json.loads(msg.data)
                method = data.get("method", "")

                # Subscribe/unsubscribe extension
                if method == "subscribe":
                    # Just acknowledge for now
                    await ws.send_json({"jsonrpc": "2.0", "id": data.get("id"),
                                        "result": {"subscribed": (data.get("params") or {}).get("topic", "default")}})
                    continue
                if method == "unsubscribe":
                    await ws.send_json({"jsonrpc": "2.0", "id": data.get("id"),
                                        "result": {"unsubscribed": True}})
                    continue

                resp = handle_rpc(data)
                if resp is not None:
                    await ws.send_json(resp)
            except Exception as e:
                await ws.send_json({"jsonrpc": "2.0", "error": {"code": -32603, "message": str(e)}})

        elif msg.type == aiohttp.WSMsgType.ERROR:
            log.error("[WS] Connection error: %s", ws.exception())
            break
        elif msg.type == aiohttp.WSMsgType.CLOSE:
            break

    return ws


# ============================================================================
# HANDLERS — Web Gateway
# ============================================================================

async def handle_gateway_index(request: web.Request) -> web.Response:
    try:
        r = require_auth(request)
        if r: return r
        _record_request()
        return _cors_json_response({
            "ok": True, "service": "arena-web-gateway", "version": "1.0.0",
            "endpoints": ["/gateway", "/gateway/tools", "/run (POST)", "/tool (POST)"],
            "mcp_proxy": "/mcp",
            "auth_required": True,
        })
    except Exception as e:
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_gateway_tools(request: web.Request) -> web.Response:
    try:
        r = require_auth(request)
        if r: return r
        _record_request()
        mcp_tools = handle_rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        return _cors_json_response({
            "ok": True,
            "whitelist_prefixes": list(GW_WHITELIST),
            "mcp_tools": mcp_tools.get("result", {}).get("tools", []) if mcp_tools else [],
        })
    except Exception as e:
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


def _gw_run_sync(cmd: str, timeout: int) -> dict:
    """Synchronous gateway command runner — returns dict result."""
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, **_subprocess_kwargs())
        return {"ok": p.returncode == 0, "exit": p.returncode,
                "stdout": p.stdout[-20000:], "stderr": p.stderr[-3000:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "exit": -1, "stdout": "", "stderr": "timeout"}
    except Exception as e:
        return {"ok": False, "exit": -2, "stdout": "", "stderr": str(e)}


async def handle_gateway_run(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    _record_request()
    try:
        data = await request.json()
    except Exception:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "bad json"}, status=400)
    cmd = (data.get("command") or data.get("cmd") or "").strip()
    if not cmd:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing command"}, status=400)
    if not gw_allowed(cmd):
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "command not in whitelist",
                                   "allowed": list(GW_WHITELIST)}, status=403)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_EXECUTOR, _gw_run_sync, cmd, int(data.get("timeout", 60)))
    return _cors_json_response(result)


async def handle_gateway_tool(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    _record_request()
    try:
        data = await request.json()
    except Exception:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "bad json"}, status=400)
    name = data.get("name")
    # Support both "arguments" (MCP spec) and "input" (common alternative)
    args = data.get("arguments") or data.get("input") or {}
    if not name:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing tool name"}, status=400)
    resp = handle_rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": name, "arguments": args}})
    return _cors_json_response({"ok": "error" not in (resp or {}), "response": resp})


# ============================================================================
# GRACEFUL SHUTDOWN
# ============================================================================

_shutdown_event: asyncio.Event | None = None


def _signal_handler(sig: int, frame: Any) -> None:
    """Signal handler for graceful shutdown."""
    sig_name = signal.Signals(sig).name if hasattr(signal, "Signals") else str(sig)
    log.info("[UnifiedBridge] Received %s, shutting down gracefully...", sig_name)
    if _shutdown_event is not None:
        _shutdown_event.set()
    # Force exit after a short delay if event loop doesn't stop
    threading.Timer(3.0, lambda: os._exit(0)).start()


# ============================================================================
# MAIN
# ============================================================================

def resolve_token(cli_token: str | None) -> tuple[str, Path]:
    """Resolve auth token: CLI arg > env var > token.txt > auto-generate.
    Returns (token, file_path_that_is_the_canonical_source_for_THIS_instance).
    file_path is the location where regen should write back."""
    # Resolve the actual file location first (env > default)
    env_file = os.environ.get("ARENA_TOKEN_FILE")
    token_file = Path(env_file).expanduser() if env_file else TOKEN_FILE

    # 1. CLI --token argument
    if cli_token:
        return cli_token, token_file
    # 2. Environment variable for token value
    env_tok = os.environ.get("ARENA_LOCAL_BRIDGE_TOKEN")
    if env_tok:
        return env_tok, token_file
    # 3. Read from token.txt
    try:
        existing = token_file.read_text(encoding="utf-8").strip()
        if existing and len(existing) >= 16:
            return existing, token_file
    except FileNotFoundError:
        pass
    except Exception:
        pass
    # 4. Auto-generate a new token and save it (to the resolved path)
    new_tok = b64_token()
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(new_tok + "\n", encoding="utf-8")
    try:
        os.chmod(token_file, 0o600)
    except Exception:
        pass
    log.info("[ArenaBridge] New token generated and saved to %s", token_file)
    return new_tok, token_file


def _daemonize() -> None:
    """Double-fork to daemonize on Linux."""
    if os.name != "nt":
        # First fork
        try:
            pid = os.fork()
            if pid > 0:
                os._exit(0)
        except OSError as e:
            log.error("[ArenaBridge] First fork failed: %s", e)
            return

        # Decouple from parent
        os.setsid()
        os.umask(0)

        # Second fork
        try:
            pid = os.fork()
            if pid > 0:
                os._exit(0)
        except OSError as e:
            log.error("[ArenaBridge] Second fork failed: %s", e)
            return

        # Redirect standard file descriptors
        sys.stdout.flush()
        sys.stderr.flush()
        devnull = open(os.devnull, "r")
        os.dup2(devnull.fileno(), sys.stdin.fileno())
        log_path = APP_DIR / "bridge.log"
        APP_DIR.mkdir(parents=True, exist_ok=True)
        log_f = open(log_path, "a", encoding="utf-8")
        os.dup2(log_f.fileno(), sys.stdout.fileno())
        os.dup2(log_f.fileno(), sys.stderr.fileno())




async def handle_v1_logs(request: web.Request) -> web.Response:
    """Return recent bridge log entries with optional level filter."""
    r = require_auth(request)
    if r: return r
    _record_request()
    try:
        level = request.query.get("level", "INFO").upper()
        lines_count = min(int(request.query.get("lines", "100")), 1000)
    except (ValueError, TypeError):
        level = "INFO"
        lines_count = 100

    valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    if level not in valid_levels:
        level = "INFO"

    log_entries = []
    try:
        if LOG_FILE.exists():
            text = LOG_FILE.read_text(encoding="utf-8", errors="replace")
            all_lines = text.splitlines()
            min_idx = valid_levels.index(level) if level in valid_levels else 1
            filter_levels = valid_levels[min_idx:]
            for line in all_lines:
                if any(f" {lv} " in line for lv in filter_levels):
                    log_entries.append(line)
            log_entries = log_entries[-lines_count:]
    except Exception as e:
        log.error("Failed to read log file: %s", e)

    return _cors_json_response({
        "ok": True,
        "log_file": str(LOG_FILE),
        "level_filter": level,
        "lines": len(log_entries),
        "entries": log_entries,
    })


def serve(args: argparse.Namespace) -> None:
    # Handle --background daemonization (Linux only)
    if getattr(args, "background", False) and os.name != "nt":
        _daemonize()

    # If --token-file was provided, set env var so resolve_token() finds it
    tf = getattr(args, "token_file", "") or ""
    if tf:
        os.environ["ARENA_TOKEN_FILE"] = tf

    token, token_file_used = resolve_token(args.token)

    root = Path(args.root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    cfg = {
        "token": token,
        "token_file": str(token_file_used),  # exact file THIS instance reads
        "profile": args.profile,
        "root": root,
        "port": args.port,
        "allow_any_cwd": args.allow_any_cwd,
        "timeout": args.timeout,
        "max_timeout": args.max_timeout,
        "max_output": args.max_output,
        "max_concurrent": args.max_concurrent,
        "semaphore": None,  # Created in on_startup after event loop is running
        "active_exec": 0,
    }

    app = make_app(cfg)

    # Set up graceful shutdown signal handlers
    global _shutdown_event
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _signal_handler)
        except (OSError, ValueError):
            pass  # Can't set signal handler in non-main thread

    log.info("Arena Unified Bridge v%s on http://%s:%s", VERSION, args.bind, args.port)
    log.info("profile=%s root=%s audit=%s max_concurrent=%s", args.profile, root, AUDIT, args.max_concurrent)
    log.info("All services multiplexed on single port: bridge, MCP, SSE, WS, gateway, dashboard, task-runner")
    log.info("Stop with Ctrl+C.")

    web.run_app(app, host=args.bind, port=args.port, print=None)


def token_cmd(_: argparse.Namespace) -> None:
    log.info("New token: %s", b64_token())


def main() -> None:
    p = argparse.ArgumentParser(description="Arena Unified Bridge")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("token", help="Generate a strong random token")
    sp.set_defaults(func=token_cmd)

    sp = sub.add_parser("serve", help="Run unified bridge")
    sp.add_argument("--bind", default="127.0.0.1",
                     help="Bind address (default: 127.0.0.1, use 0.0.0.0 for remote access)")
    sp.add_argument("--port", type=int, default=8765)
    sp.add_argument("--token")
    sp.add_argument("--token-file", dest="token_file", default="",
                     help="Path to token file (default: ~/arena-bridge/token.txt)")
    sp.add_argument("--root", default=str(Path.home()))
    sp.add_argument("--allow-any-cwd", action="store_true")
    sp.add_argument("--profile", choices=["cautious", "owner-shell"], default="cautious")
    sp.add_argument("--timeout", type=int, default=60)
    sp.add_argument("--max-timeout", type=int, default=600)
    sp.add_argument("--max-output", type=int, default=DEFAULT_MAX_OUTPUT)
    sp.add_argument("--max-concurrent", type=int, default=DEFAULT_MAX_CONCURRENT)
    sp.add_argument("--background", action="store_true",
                     help="Daemonize on Linux (fork + detach)")
    sp.set_defaults(func=serve)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
