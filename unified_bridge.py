#!/usr/bin/env python3
"""
Arena Unified Bridge v1.5.0

Single asyncio-based process that multiplexes ALL services on one port (8765):
  - /health          GET   Public health check
  - /                GET   API index with endpoints list
  - /v1/version      GET   Version info
  - /v1/info         GET   Bridge info (auth required)
  - /v1/status       GET   Bridge status (auth required)
  - /v1/sysinfo      GET   Hardware/system info (auth required)
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
  - All commands logged to ~/.arena-local-bridge/audit.jsonl
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

# ============================================================================
# VERSION & CONSTANTS
# ============================================================================
VERSION = "1.5.1"
AUDIT_CMD_LIMIT = 4000
APP_DIR = Path.home() / ".arena-local-bridge"
TOKEN_FILE = Path.home() / "arena-local-bridge" / "token.txt"
AUDIT = APP_DIR / "audit.jsonl"
RUN_DIR = APP_DIR / "runs"
MAX_BODY = 1024 * 1024
DEFAULT_MAX_OUTPUT = 2 * 1024 * 1024
DEFAULT_MAX_CONCURRENT = 3

ACTIVE_PROCESSES: dict[str, dict] = {}
audit_lock = threading.Lock()

# Thread pool executor for running blocking I/O in async handlers
_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="bridge_io")

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
BIN = os.path.join(HOME, "arena-agent", "bin")

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


def _record_request(duration: float = 0.0, is_exec: bool = False, is_error: bool = False) -> None:
    """Record a request in the bridge metrics."""
    with _metrics_lock:
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


def _cors_json_response(data: Any, status: int = 200, **kwargs: Any) -> web.Response:
    """Return a JSON response with CORS headers."""
    return web.json_response(data, status=status, headers={
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Arena-Token, Mcp-Session-Id",
    }, **kwargs)


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
    p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def run_sd(argv: list[str], timeout: int = 60) -> tuple[int, str, str]:
    """Run command via sd-exec (Linux) or directly (Windows)."""
    if platform.system() == "Windows":
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, shell=True)
        return p.returncode, p.stdout, p.stderr
    else:
        sd = os.path.join(BIN, "sd-exec")
        p = subprocess.run([sd, "--timeout", str(timeout), "--"] + argv,
                           capture_output=True, text=True, timeout=timeout + 10)
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
            if platform.system() == "Windows":
                rc, out, err = run_sd(["cmd", "/c", args["cmd"]], timeout=args.get("timeout", 60))
            else:
                rc, out, err = run_sd(["bash", "-lc", args["cmd"]], timeout=args.get("timeout", 60))
            return text_content(json.dumps({"exit": rc, "stdout": out[-15000:], "stderr": err[-5000:]}, ensure_ascii=False))
        if name == "fs.read":
            p = os.path.expanduser(args["path"])
            with open(p, "rb") as f:
                data = f.read(args.get("max_bytes", 200000))
            return text_content(data.decode("utf-8", "replace"))
        if name == "fs.write":
            p = os.path.expanduser(args["path"])
            os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(args["content"])
            return text_content(f"wrote {len(args['content'])} bytes to {p}")
        if name == "fs.list":
            p = os.path.expanduser(args["path"])
            return text_content(json.dumps(sorted(os.listdir(p))))
        if name == "browser.search":
            rc, out, err = run_local([sys.executable, os.path.join(BIN, "py_browser.py"),
                                       "search", args["query"], "--n", str(args.get("n", 5))], timeout=30)
            return text_content(out or err)
        if name == "browser.read":
            rc, out, err = run_local([sys.executable, os.path.join(BIN, "py_browser.py"),
                                       "read", args["url"]], timeout=30)
            return text_content(out or err)
        if name == "browser.shot":
            import shutil as _shutil
            shots = os.path.join(HOME, "arena-agent", "reports", "shots")
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
                (_shutil.which(c) or (c if os.path.exists(c) else None))
                for c in chrome_candidates if _shutil.which(c) or os.path.exists(c)
            ) or "chrome.exe"
            rc, out, err = run_sd([chrome_exe, "--headless=new", "--no-sandbox", "--disable-gpu",
                                    f"--user-data-dir={ud}", "--window-size=1366,768",
                                    f"--screenshot={png}", args["url"]], timeout=45)
            return text_content(json.dumps({"ok": rc == 0, "screenshot": png, "url": args["url"]}))
        if name == "mem.set":
            tags = args.get("tags") or []
            cmd_args = [os.path.join(BIN, "agentctl"), "mem", "set", args["key"], args["value"]]
            if tags:
                cmd_args += ["--tags"] + list(tags)
            rc, out, err = run_local(cmd_args, timeout=15)
            return text_content(out or err)
        if name == "mem.get":
            rc, out, err = run_local([os.path.join(BIN, "agentctl"), "mem", "get", args["query"]], timeout=15)
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
    return any(cmd.startswith(p) for p in GW_WHITELIST)


# ============================================================================
# TASK RUNNER (integrated asyncio background)
# ============================================================================

ROOT_AGENT = Path(os.environ.get("ARENA_AGENT_HOME", str(Path.home() / "arena-agent"))).expanduser()
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
MEMORY_FILE = Path.home() / "arena-agent" / "memory" / "facts.jsonl"
MISSIONS_DIR = Path.home() / "arena-agent" / "missions"
REPORTS_DIR = Path.home() / "arena-agent" / "reports"
BACKUPS_DIR = ROOT_AGENT / "backups"


def task_ensure_dirs():
    for p in [INBOX, RUNNING, DONE, FAILED]:
        p.mkdir(parents=True, exist_ok=True)


async def task_run_one(task_path: Path) -> bool:
    """Process a single task JSON file asynchronously."""
    try:
        task = json.loads(task_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[TaskRunner] Failed to read {task_path}: {e}", file=sys.stderr)
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

    print(f"[TaskRunner] {tid}: {state} exit={exit_code} dur={duration}s", flush=True)
    return True


async def task_runner_loop(app: web.Application):
    """Background task: watches INBOX for new tasks every 5 seconds."""
    task_ensure_dirs()
    print("[TaskRunner] Watching", INBOX, flush=True)
    while True:
        try:
            task_ensure_dirs()
            for p in sorted(INBOX.glob("*.json"))[:3]:
                await task_run_one(p)
        except Exception as e:
            print(f"[TaskRunner] Error: {e}", file=sys.stderr)
        await asyncio.sleep(5)


# ============================================================================
# APP CONFIG
# ============================================================================

def make_app(cfg: dict) -> web.Application:
    app = web.Application(client_max_size=50 * 1024 * 1024)
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
    app.router.add_get("/v1/sys/funnel", handle_v1_sys_funnel)
    app.router.add_get("/v1/browser/dump", handle_v1_browser_dump)
    app.router.add_get("/v1/browser/fetch", handle_v1_browser_fetch)
    app.router.add_get("/v1/browser/head", handle_v1_browser_head)
    app.router.add_get("/v1/recall", handle_v1_recall)
    app.router.add_get("/v1/recall/digest", handle_v1_recall_digest)
    app.router.add_get("/v1/audit/stats", handle_v1_audit_stats)
    app.router.add_get("/v1/tasks", handle_v1_tasks_get)
    app.router.add_post("/v1/tasks", handle_v1_tasks_post)
    app.router.add_post("/v1/tasks/clean", handle_v1_tasks_clean)
    app.router.add_post("/v1/backup", handle_v1_backup)
    app.router.add_get("/v1/skills", handle_v1_skills)
    app.router.add_post("/v1/skills/run", handle_v1_skills_run)
    app.router.add_get("/v1/hooks", handle_v1_hooks)
    app.router.add_get("/v1/agents", handle_v1_agents)
    app.router.add_get("/v1/subagents", handle_v1_subagents)
    app.router.add_post("/v1/subagents/spawn", handle_v1_subagents_spawn)
    app.router.add_get("/v1/mission/show", handle_v1_mission_show)
    app.router.add_get("/v1/metrics", handle_v1_metrics)

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
    print(f"[UnifiedBridge v{VERSION}] Background task runner started", flush=True)


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
                "GET /v1/recall?q=&top=5", "GET /v1/recall/digest",
                "GET /v1/tasks?status=&limit=20", "POST /v1/tasks", "POST /v1/tasks/clean",
                "POST /v1/backup",
                "GET /v1/skills", "POST /v1/skills/run",
                "GET /v1/hooks", "GET /v1/agents",
                "GET /v1/subagents", "POST /v1/subagents/spawn",
                "GET /v1/sys/svc", "GET /v1/sys/funnel",
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
            "wmic cpu get NumberOfCores,NumberOfLogicalProcessors", shell=True)
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

        load = getattr(os, "getloadavg", lambda: (0.0, 0.0, 0.0))()
        return _cors_json_response({
            "ok": True,
            "cpu_cores": cpu_physical,
            "cpu_threads": cpu_logical,
            "load_avg": list(load),
            "mem_total_mb": mem_total // (1024 * 1024),
            "mem_avail_mb": mem_avail // (1024 * 1024),
            "disk_total_gb": disk.total // (1024 ** 3),
            "disk_free_gb": disk.free // (1024 ** 3),
        })
    except Exception as e:
        _record_request(is_error=True)
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
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": f"invalid json: {e}"}, status=400)

    if not isinstance(data, dict):
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": "JSON must be object"}, status=400)

    request_id = str(data.get("request_id") or uuid.uuid4())
    cmd = str(data.get("cmd", "")).strip()
    if not cmd:
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": "missing cmd", "request_id": request_id}, status=400)

    # Safety checks
    reason = blocked_reason(cmd)
    if reason:
        audit({"type": "exec_blocked", "request_id": request_id, "cmd": cmd, "reason": reason,
                "client": request.remote or "127.0.0.1"})
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": reason, "request_id": request_id}, status=403)

    profile = cfg["profile"]
    fw = first_word(cmd)
    if profile == "cautious" and fw not in CAUTIOUS_ALLOW:
        reason = f"command '{fw}' not in cautious allowlist; use --profile owner-shell"
        audit({"type": "exec_blocked", "request_id": request_id, "cmd": cmd, "reason": reason,
                "client": request.remote or "127.0.0.1"})
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": reason, "request_id": request_id}, status=403)

    root: Path = cfg["root"]
    cwd_raw = str(data.get("cwd") or root)
    cwd = Path(cwd_raw).expanduser()
    if not cwd.is_absolute():
        cwd = root / cwd
    if not cfg["allow_any_cwd"] and not under_root(cwd, root):
        _record_request(is_error=True)
        return _cors_json_response(
            {"ok": False, "error": f"cwd must be under root {root}", "request_id": request_id}, status=403)
    if not cwd.exists() or not cwd.is_dir():
        _record_request(is_error=True)
        return _cors_json_response(
            {"ok": False, "error": f"cwd does not exist: {cwd}", "request_id": request_id}, status=400)

    timeout = min(int(data.get("timeout", cfg["timeout"])), cfg["max_timeout"])
    max_output = min(int(data.get("max_output", DEFAULT_MAX_OUTPUT)), cfg["max_output"])
    env_extra = data.get("env") if isinstance(data.get("env"), dict) else {}
    env = os.environ.copy()
    env.update({str(k): str(v) for k, v in env_extra.items()})

    sem: asyncio.Semaphore = cfg["semaphore"]
    if sem.locked() and cfg["active_exec"] >= cfg["max_concurrent"]:
        _record_request(is_error=True)
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
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": "invalid json"}, status=400)
    target_id = data.get("request_id")
    if not target_id or target_id not in ACTIVE_PROCESSES:
        _record_request(is_error=True)
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
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": "missing path"}, status=400)
    target_path = Path(target).expanduser()
    if not target_path.is_absolute():
        target_path = request.app["cfg"]["root"] / target_path
    try:
        body = await request.read()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(body)
        audit({"type": "file_upload", "path": str(target_path), "bytes": len(body)})
        _record_request()
        return _cors_json_response({"ok": True, "path": str(target_path), "bytes": len(body)})
    except Exception as e:
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": repr(e)}, status=500)


async def handle_v1_download(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    qs = parse_qs(request.query_string)
    target = qs.get("path", [""])[0]
    if not target:
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": "missing path"}, status=400)
    target_path = Path(target).expanduser()
    if not target_path.is_absolute():
        target_path = request.app["cfg"]["root"] / target_path
    if not target_path.exists() or not target_path.is_file():
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": "file not found"}, status=404)
    try:
        audit({"type": "file_download", "path": str(target_path), "bytes": target_path.stat().st_size})
        _record_request()
        return web.FileResponse(target_path, headers={
            "Content-Disposition": f'attachment; filename="{target_path.name}"',
            "Access-Control-Allow-Origin": "*",
        })
    except Exception as e:
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": repr(e)}, status=500)


# ============================================================================
# HANDLER — Dashboard GUI
# ============================================================================

async def handle_gui(request: web.Request) -> web.Response:
    try:
        cfg = request.app["cfg"]
        # Try multiple locations for the dashboard
        candidates = [
            cfg["root"] / "arena-agent" / "dashboard" / "index.html",
            Path.home() / "arena-agent" / "dashboard" / "index.html",
            Path(__file__).parent / "dashboard" / "index.html",
            Path(__file__).parent / "index.html",
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


    # ============================================================================
    # HANDLERS — Dashboard API endpoints
    # ============================================================================
    except Exception as e:
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)

def _load_facts() -> list[dict]:
    """Load memory facts from JSONL."""
    if not MEMORY_FILE.exists():
        return []
    items = []
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        items.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except Exception:
        pass
    return items


def _write_fact(entry: dict) -> None:
    """Append a fact entry to the memory file."""
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MEMORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


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
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": f"invalid json: {e}"}, status=400)
    key = str(data.get("key", "")).strip()
    value = str(data.get("value", "")).strip()
    if not key:
        _record_request(is_error=True)
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
    for name, path in [("Agent dir", Path.home() / "arena-agent"), ("Bridge dir", Path.home() / "arena-local-bridge"),
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
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": "missing q parameter"}, status=400)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _browser_search_sync, query, n)
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


def _browser_read_sync(url: str) -> dict:
    """Synchronous URL read with readability extraction — returns dict result."""
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
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": "missing url parameter"}, status=400)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _browser_read_sync, url)
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# ============================================================================
# HANDLERS — v1.5.0 New Endpoints
# ============================================================================

# --- /v1/sys/svc GET — Service status ---

def _sys_svc_sync() -> dict:
    """Synchronous helper to check service status."""
    result: dict[str, Any] = {"ok": True}

    # Check if bridge is running as scheduled task (Windows) or systemd service (Linux)
    scheduled_task = False
    scheduled_detail = ""
    if sys.platform == "win32":
        try:
            out = subprocess.check_output(
                'schtasks /query /tn "ArenaBridge" /fo LIST', shell=True, stderr=subprocess.DEVNULL)
            if b"ArenaBridge" in out:
                scheduled_task = True
                scheduled_detail = "Windows scheduled task found"
        except Exception:
            scheduled_detail = "No Windows scheduled task"
    else:
        # Check systemd
        try:
            out = subprocess.check_output(
                ["systemctl", "is-active", "arena-bridge"], stderr=subprocess.DEVNULL)
            status = out.decode("utf-8", errors="replace").strip()
            if status == "active":
                scheduled_task = True
                scheduled_detail = f"systemd service: {status}"
            else:
                scheduled_detail = f"systemd service: {status}"
        except Exception:
            # Check for cron
            try:
                out = subprocess.check_output(["crontab", "-l"], stderr=subprocess.DEVNULL)
                if b"unified_bridge" in out or b"arena" in out:
                    scheduled_task = True
                    scheduled_detail = "cron job found"
                else:
                    scheduled_detail = "No cron/systemd service"
            except Exception:
                scheduled_detail = "No scheduled task/service detected"

    result["scheduled_task"] = {"running": scheduled_task, "detail": scheduled_detail}

    # Check running bridge processes
    bridge_procs = []
    try:
        if sys.platform == "win32":
            out = subprocess.check_output(
                'wmic process where "commandline like \'%unified_bridge%\'" get processid,commandline /format:list',
                shell=True, stderr=subprocess.DEVNULL, text=True)
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("CommandLine=") or line.startswith("ProcessId="):
                    bridge_procs.append(line)
        else:
            out = subprocess.check_output(
                ["ps", "aux"], stderr=subprocess.DEVNULL, text=True)
            for line in out.splitlines():
                if "unified_bridge" in line and "grep" not in line:
                    bridge_procs.append(line.strip()[:200])
    except Exception:
        pass
    result["bridge_processes"] = {"count": len(bridge_procs), "details": bridge_procs[:10]}

    # Check Tailscale status
    tailscale = {"installed": False, "connected": False, "detail": ""}
    try:
        out = subprocess.check_output(["tailscale", "status"], stderr=subprocess.DEVNULL, text=True)
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
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/sys/funnel GET — Tailscale Funnel status ---

def _sys_funnel_sync() -> dict:
    """Synchronous helper to check Tailscale funnel status."""
    result: dict[str, Any] = {"ok": True, "tailscale": {}, "funnel": {}}

    # Run tailscale status
    try:
        out = subprocess.check_output(["tailscale", "status"], stderr=subprocess.STDOUT, text=True)
        result["tailscale"]["status"] = out.strip()[:2000]
        result["tailscale"]["connected"] = bool(out.strip())
    except FileNotFoundError:
        result["tailscale"]["error"] = "tailscale not found"
    except Exception as e:
        result["tailscale"]["error"] = str(e)[:500]

    # Run tailscale funnel status
    try:
        out = subprocess.check_output(["tailscale", "funnel", "status"], stderr=subprocess.STDOUT, text=True)
        result["funnel"]["status"] = out.strip()[:2000]
        result["funnel"]["active"] = "listening" in out.lower() or "serving" in out.lower()
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
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/browser/dump GET — Full page dump with links ---

def _browser_dump_sync(url: str) -> dict:
    """Fetch URL, extract text + all <a href> links."""
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
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": "missing url parameter"}, status=400)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _browser_dump_sync, url)
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/browser/fetch GET — Raw content fetch ---

def _browser_fetch_sync(url: str) -> dict:
    """Fetch URL, return raw content."""
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
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": "missing url parameter"}, status=400)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _browser_fetch_sync, url)
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/browser/head GET — HTTP HEAD ---

def _browser_head_sync(url: str) -> dict:
    """Do HTTP HEAD request, return headers."""
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
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": "missing url parameter"}, status=400)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _browser_head_sync, url)
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True)
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
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": "missing q parameter"}, status=400)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _recall_sync, query, top)
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True)
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
        _record_request(is_error=True)
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
        _record_request(is_error=True)
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
        _record_request(is_error=True)
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
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": f"invalid json: {e}"}, status=400)
    cmd = data.get("cmd", "")
    if not cmd:
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": "missing cmd"}, status=400)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _task_submit_sync, data)
        audit({"type": "task_submit", "task_id": result.get("task_id"), "cmd": cmd})
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True)
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
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/backup POST — Create backup ---

def _backup_sync(paths: list[str], name: str) -> dict:
    """Create zip of specified directories."""
    SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".next", ".turbo", ".arena", "venv"}
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)

    if not name:
        name = f"backup-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    if not name.endswith(".zip"):
        name += ".zip"

    backup_path = BACKUPS_DIR / name
    file_count = 0

    total_size = 0
    MAX_BACKUP_SIZE = 100 * 1024 * 1024  # 100MB max backup
    with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for path_str in paths:
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
                    dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                    for fname in files:
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
    paths = data.get("paths", [str(Path.home() / "arena-agent")])
    name = data.get("name", "")
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _backup_sync, paths, name)
        audit({"type": "backup", "name": name, "paths": paths, "size": result.get("size", 0),
               "file_count": result.get("file_count", 0)})
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/skills GET — List skills ---

def _skills_list_sync() -> dict:
    """Scan arena-agent/skills/ directory for skill definitions."""
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
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/skills/run POST — Run a skill ---

def _skills_run_sync(name: str, args: list[str]) -> dict:
    """Execute a skill via agentctl."""
    cmd_args = [os.path.join(BIN, "agentctl"), "skill", "run", name] + list(args)
    try:
        p = subprocess.run(cmd_args, capture_output=True, text=True, timeout=300)
        return {"ok": p.returncode == 0, "exit_code": p.returncode,
                "stdout": p.stdout[-15000:], "stderr": p.stderr[-3000:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "exit_code": -1, "stdout": "", "stderr": "timeout"}
    except Exception as e:
        return {"ok": False, "exit_code": -2, "stdout": "", "stderr": str(e)}


async def handle_v1_skills_run(request: web.Request) -> web.Response:
    """POST /v1/skills/run — Run a skill. Body: {name, args?: []}."""
    r = require_auth(request)
    if r: return r
    _record_request()
    try:
        data = await request.json()
    except Exception as e:
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": f"invalid json: {e}"}, status=400)
    name = data.get("name", "")
    if not name:
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": "missing name"}, status=400)
    skill_args = data.get("args") or []
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _skills_run_sync, name, skill_args)
        audit({"type": "skill_run", "name": name, "args": skill_args, "ok": result.get("ok", False)})
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/hooks GET — List hooks ---

def _hooks_list_sync() -> dict:
    """Read hooks from arena-agent/hooks/."""
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
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/agents GET — List agent configs ---

def _agents_list_sync() -> dict:
    """Scan arena-agent/agents/ for agent config files."""
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
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/subagents GET — List subagents ---

def _subagents_list_sync() -> dict:
    """Read from arena-agent/subagents/."""
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
        _record_request(is_error=True)
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
        p = subprocess.run(cmd_args, capture_output=True, text=True, timeout=timeout + 30)
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
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": f"invalid json: {e}"}, status=400)
    cmd = data.get("cmd", "")
    if not cmd:
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": "missing cmd"}, status=400)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _subagents_spawn_sync, data)
        audit({"type": "subagent_spawn", "cmd": cmd, "name": data.get("name", ""),
               "ok": result.get("ok", False)})
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/mission/show GET — Show mission details ---

def _mission_show_sync(name: str) -> dict:
    """Read and return mission file content."""
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
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": "missing name parameter"}, status=400)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _mission_show_sync, name)
        if not result.get("ok"):
            _record_request(is_error=True)
            return _cors_json_response(result, status=404)
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True)
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
    _record_request()
    try:
        msg = await request.json()
    except Exception:
        _record_request(is_error=True)
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
    _record_request()
    try:
        msg = await request.json()
    except Exception:
        _record_request(is_error=True)
        return _cors_json_response({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}}, status=400)

    # Process the RPC message
    handle_rpc(msg)
    return web.Response(status=202, headers={"Access-Control-Allow-Origin": "*"})


# ============================================================================
# HANDLER — MCP WebSocket
# ============================================================================

async def handle_ws(request: web.Request) -> web.WebSocketResponse:
    """WebSocket MCP transport — full-duplex JSON-RPC."""
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
            print(f"[WS] Connection error: {ws.exception()}", file=sys.stderr)
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
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
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
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": "bad json"}, status=400)
    cmd = (data.get("command") or "").strip()
    if not cmd:
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": "missing command"}, status=400)
    if not gw_allowed(cmd):
        _record_request(is_error=True)
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
        _record_request(is_error=True)
        return _cors_json_response({"ok": False, "error": "bad json"}, status=400)
    name = data.get("name")
    args = data.get("arguments") or {}
    if not name:
        _record_request(is_error=True)
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
    print(f"\n[UnifiedBridge] Received {sig_name}, shutting down gracefully...", flush=True)
    if _shutdown_event is not None:
        _shutdown_event.set()
    # Force exit after a short delay if event loop doesn't stop
    threading.Timer(3.0, lambda: os._exit(0)).start()


# ============================================================================
# MAIN
# ============================================================================

def resolve_token(cli_token: str | None) -> str:
    """Resolve auth token: CLI arg > env var > token.txt > auto-generate new one."""
    # 1. CLI --token argument
    if cli_token:
        return cli_token
    # 2. Environment variable
    env_tok = os.environ.get("ARENA_LOCAL_BRIDGE_TOKEN")
    if env_tok:
        return env_tok
    # 3. Read from token.txt
    try:
        existing = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if existing and len(existing) >= 16:
            return existing
    except FileNotFoundError:
        pass
    except Exception:
        pass
    # 4. Auto-generate a new token and save it
    new_tok = b64_token()
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(new_tok + "\n", encoding="utf-8")
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except Exception:
        pass
    print(f"[ArenaBridge] New token generated and saved to {TOKEN_FILE}", flush=True)
    return new_tok


def _daemonize() -> None:
    """Double-fork to daemonize on Linux."""
    if os.name != "nt":
        # First fork
        try:
            pid = os.fork()
            if pid > 0:
                os._exit(0)
        except OSError as e:
            print(f"[ArenaBridge] First fork failed: {e}", file=sys.stderr)
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
            print(f"[ArenaBridge] Second fork failed: {e}", file=sys.stderr)
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


def serve(args: argparse.Namespace) -> None:
    # Handle --background daemonization (Linux only)
    if getattr(args, "background", False) and os.name != "nt":
        _daemonize()

    token = resolve_token(args.token)

    root = Path(args.root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    cfg = {
        "token": token,
        "profile": args.profile,
        "root": root,
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

    print(f"Arena Unified Bridge v{VERSION} on http://{args.bind}:{args.port}", flush=True)
    print(f"profile={args.profile} root={root} audit={AUDIT} max_concurrent={args.max_concurrent}", flush=True)
    print("All services multiplexed on single port: bridge, MCP, SSE, WS, gateway, dashboard, task-runner", flush=True)
    print("Stop with Ctrl+C.", flush=True)

    web.run_app(app, host=args.bind, port=args.port, print=None)


def token_cmd(_: argparse.Namespace) -> None:
    print(b64_token())


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
