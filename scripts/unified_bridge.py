#!/usr/bin/env python3
"""
Arena Unified Bridge v1.0

Single asyncio-based process that multiplexes ALL services on one port (8765):
  - /health          GET   Public health check
  - /                GET   API index with endpoints list
  - /v1/info         GET   Bridge info (auth required)
  - /v1/status       GET   Bridge status (auth required)
  - /v1/sysinfo      GET   Hardware/system info (auth required)
  - /v1/ps           GET   Active processes (auth required)
  - /v1/audit        GET   Audit log (auth required)
  - /v1/exec         POST  Execute command (auth required)
  - /v1/kill         POST  Kill a running process (auth required)
  - /v1/upload       POST  Upload file (auth required)
  - /v1/download     GET   Download file (auth required)
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
  - Binds to 127.0.0.1 by default
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
import base64
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
from asyncio import subprocess as aiosubprocess
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import aiohttp
from aiohttp import web

# ============================================================================
# VERSION & CONSTANTS
# ============================================================================
VERSION = "1.2.0"
AUDIT_CMD_LIMIT = 4000
APP_DIR = Path.home() / ".arena-local-bridge"
AUDIT = APP_DIR / "audit.jsonl"
RUN_DIR = APP_DIR / "runs"
MAX_BODY = 1024 * 1024
DEFAULT_MAX_OUTPUT = 2 * 1024 * 1024
DEFAULT_MAX_CONCURRENT = 3

ACTIVE_PROCESSES: dict[str, dict] = {}
audit_lock = threading.Lock()

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
# mcp_sessions_lock removed - sessions managed via app["mcp_sessions"] in single-threaded asyncio


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

@web.middleware
async def cors_middleware(request: web.Request, handler):
    """CORS middleware: adds headers to all responses, handles OPTIONS preflight."""
    origin = request.headers.get("Origin", "")
    
    # Handle OPTIONS preflight
    if request.method == "OPTIONS":
        resp = web.Response(status=204)
    else:
        try:
            resp = await handler(request)
        except web.HTTPException as exc:
            resp = exc
    
    # Add CORS headers to all responses
    if origin:
        resp.headers["Access-Control-Allow-Origin"] = origin
    else:
        resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Arena-Token, Mcp-Session-Id, Last-Event-ID"
    resp.headers["Access-Control-Expose-Headers"] = "Mcp-Session-Id"
    resp.headers["Access-Control-Max-Age"] = "86400"
    return resp


def make_app(cfg: dict) -> web.Application:
    app = web.Application(
        client_max_size=50 * 1024 * 1024,
        middlewares=[cors_middleware],
    )
    app["cfg"] = cfg
    app["mcp_sessions"] = {}

    # ---- Public endpoints ----
    app.router.add_get("/", handle_index)
    app.router.add_get("/health", handle_health)

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
    """Start background task runner."""
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
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
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
    return web.json_response({
        "ok": True,
        "service": "arena-unified-bridge",
        "version": VERSION,
        "endpoints": [
            "/health", "/v1/info", "/v1/status", "/v1/sysinfo",
            "/v1/ps", "/v1/audit?lines=100",
            "POST /v1/exec", "POST /v1/kill",
            "POST /v1/upload?path=", "GET /v1/download?path=",
            "/gui", "POST /mcp", "DELETE /mcp",
            "GET /sse", "POST /messages", "GET /ws",
            "/gateway", "/gateway/tools", "POST /run", "POST /tool",
        ],
        "auth_required_for_exec": True,
    })


async def handle_health(request: web.Request) -> web.Response:
    cfg = request.app["cfg"]
    s = common_status(cfg)
    for k in ["audit", "active_exec", "max_concurrent", "python"]:
        s.pop(k, None)
    return web.json_response(s)


# ============================================================================
# HANDLERS — v1 API
# ============================================================================

async def handle_v1_info(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    return web.json_response(common_status(request.app["cfg"]))


async def handle_v1_status(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    return web.json_response(common_status(request.app["cfg"]))


async def handle_v1_sysinfo(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
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

        load = getattr(os, "getloadavg", lambda: (0.0, 0.0, 0.0))()
        return web.json_response({
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
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_ps(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    ps_list = []
    for req_id, info in ACTIVE_PROCESSES.items():
        ps_list.append({
            "request_id": req_id,
            "pid": info["pid"],
            "cmd": info["cmd"][:200],
            "uptime_sec": round(time.time() - info["start"], 1),
        })
    return web.json_response({"ok": True, "processes": ps_list, "count": len(ps_list)})


async def handle_v1_audit(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    qs = parse_qs(request.query_string)
    try:
        n = int(qs.get("lines", ["100"])[0])
    except ValueError:
        n = 100
    rows = []
    for line in read_tail(AUDIT, n):
        try:
            rows.append(json.loads(line))
        except Exception:
            rows.append({"raw": line})
    return web.json_response({"ok": True, "lines": len(rows), "audit": str(AUDIT), "events": rows})


async def handle_v1_exec(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    cfg = request.app["cfg"]

    try:
        data = await request.json()
    except Exception as e:
        return web.json_response({"ok": False, "error": f"invalid json: {e}"}, status=400)

    if not isinstance(data, dict):
        return web.json_response({"ok": False, "error": "JSON must be object"}, status=400)

    request_id = str(data.get("request_id") or uuid.uuid4())
    cmd = str(data.get("cmd", "")).strip()
    if not cmd:
        return web.json_response({"ok": False, "error": "missing cmd", "request_id": request_id}, status=400)

    # Reject duplicate request_id to prevent ACTIVE_PROCESSES collision
    if request_id in ACTIVE_PROCESSES:
        return web.json_response(
            {"ok": False, "error": f"request_id {request_id} already in use", "request_id": request_id}, status=409)

    # Safety checks
    reason = blocked_reason(cmd)
    if reason:
        audit({"type": "exec_blocked", "request_id": request_id, "cmd": cmd, "reason": reason,
                "client": request.remote or "127.0.0.1"})
        return web.json_response({"ok": False, "error": reason, "request_id": request_id}, status=403)

    profile = cfg["profile"]
    fw = first_word(cmd)
    if profile == "cautious" and fw not in CAUTIOUS_ALLOW:
        reason = f"command '{fw}' not in cautious allowlist; use --profile owner-shell"
        audit({"type": "exec_blocked", "request_id": request_id, "cmd": cmd, "reason": reason,
                "client": request.remote or "127.0.0.1"})
        return web.json_response({"ok": False, "error": reason, "request_id": request_id}, status=403)

    root: Path = cfg["root"]
    cwd_raw = str(data.get("cwd") or root)
    cwd = Path(cwd_raw).expanduser()
    if not cwd.is_absolute():
        cwd = root / cwd
    if not cfg["allow_any_cwd"] and not under_root(cwd, root):
        return web.json_response(
            {"ok": False, "error": f"cwd must be under root {root}", "request_id": request_id}, status=403)
    if not cwd.exists() or not cwd.is_dir():
        return web.json_response(
            {"ok": False, "error": f"cwd does not exist: {cwd}", "request_id": request_id}, status=400)

    timeout = min(int(data.get("timeout", cfg["timeout"])), cfg["max_timeout"])
    max_output = min(int(data.get("max_output", DEFAULT_MAX_OUTPUT)), cfg["max_output"])
    env_extra = data.get("env") if isinstance(data.get("env"), dict) else {}
    env = os.environ.copy()
    env.update({str(k): str(v) for k, v in env_extra.items()})

    sem: asyncio.Semaphore = cfg["semaphore"]
    if sem.locked() and cfg["active_exec"] >= cfg["max_concurrent"]:
        return web.json_response(
            {"ok": False, "error": "too many concurrent exec requests", "request_id": request_id}, status=429)

    await sem.acquire()
    cfg["active_exec"] += 1
    sem_acquired = True

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

        return web.json_response({
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
        return web.json_response({"ok": False, "request_id": request_id, "error": repr(e), "duration_sec": duration}, status=500)

    finally:
        ACTIVE_PROCESSES.pop(request_id, None)
        if sem_acquired:
            cfg["active_exec"] -= 1
            sem.release()


async def handle_v1_kill(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid json"}, status=400)
    target_id = data.get("request_id")
    if not target_id or target_id not in ACTIVE_PROCESSES:
        return web.json_response({"ok": False, "error": "process not found"}, status=404)
    info = ACTIVE_PROCESSES[target_id]
    try:
        os.kill(info["pid"], signal.SIGTERM if os.name != "nt" else signal.CTRL_BREAK_EVENT)
    except Exception:
        pass
    audit({"type": "process_killed", "target_request_id": target_id, "client": request.remote or "127.0.0.1"})
    return web.json_response({"ok": True, "killed": target_id})


async def handle_v1_upload(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    qs = parse_qs(request.query_string)
    target = qs.get("path", [""])[0]
    if not target:
        return web.json_response({"ok": False, "error": "missing path"}, status=400)
    target_path = Path(target).expanduser()
    if not target_path.is_absolute():
        target_path = request.app["cfg"]["root"] / target_path
    try:
        body = await request.read()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(body)
        audit({"type": "file_upload", "path": str(target_path), "bytes": len(body)})
        return web.json_response({"ok": True, "path": str(target_path), "bytes": len(body)})
    except Exception as e:
        return web.json_response({"ok": False, "error": repr(e)}, status=500)


async def handle_v1_download(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    qs = parse_qs(request.query_string)
    target = qs.get("path", [""])[0]
    if not target:
        return web.json_response({"ok": False, "error": "missing path"}, status=400)
    target_path = Path(target).expanduser()
    if not target_path.is_absolute():
        target_path = request.app["cfg"]["root"] / target_path
    if not target_path.exists() or not target_path.is_file():
        return web.json_response({"ok": False, "error": "file not found"}, status=404)
    try:
        audit({"type": "file_download", "path": str(target_path), "bytes": target_path.stat().st_size})
        return web.FileResponse(target_path, headers={
            "Content-Disposition": f'attachment; filename="{target_path.name}"'
        })
    except Exception as e:
        return web.json_response({"ok": False, "error": repr(e)}, status=500)


# ============================================================================
# HANDLER — Dashboard GUI
# ============================================================================

async def handle_gui(request: web.Request) -> web.Response:
    cfg = request.app["cfg"]
    html_path = cfg["root"] / "arena-agent" / "dashboard" / "index.html"
    if html_path.exists():
        html = html_path.read_text(encoding="utf-8")
        html = html.replace("{{TOKEN}}", cfg["token"])
        return web.Response(text=html, content_type="text/html", charset="utf-8")
    return web.Response(text="Dashboard not found", status=404)


# ============================================================================
# HANDLERS — MCP Streamable HTTP
# ============================================================================

async def handle_mcp_post(request: web.Request) -> web.Response:
    """MCP Streamable HTTP — main endpoint."""
    try:
        msg = await request.json()
    except Exception:
        return web.json_response({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}}, status=400)

    # New session on initialize
    session_hdr = request.headers.get("Mcp-Session-Id", "")
    if msg.get("method") == "initialize":
        session = sid()
        request.app["mcp_sessions"][session] = {"created": now_ms()}
        resp = handle_rpc(msg)
        return web.json_response(resp, headers={"Mcp-Session-Id": session})

    resp = handle_rpc(msg)
    if resp is None:
        return web.json_response({}, status=204)
    return web.json_response(resp)


async def handle_mcp_delete(request: web.Request) -> web.Response:
    """Close MCP session."""
    sess = request.headers.get("Mcp-Session-Id", "")
    request.app["mcp_sessions"].pop(sess, None)
    return web.Response(status=204)


# ============================================================================
# HANDLERS — MCP SSE Legacy
# ============================================================================

async def handle_sse(request: web.Request) -> web.Response:
    """SSE legacy transport — open event stream."""
    session = sid()
    request.app["mcp_sessions"][session] = {"created": now_ms(), "stream": None}

    resp = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # CORS headers now handled by cors_middleware
        }
    )
    await resp.prepare(request)
    request.app["mcp_sessions"][session]["stream"] = resp
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
    """SSE legacy peer message endpoint - routes RPC response back through the SSE stream."""
    try:
        msg = await request.json()
    except Exception:
        return web.json_response({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}}, status=400)

    # Process the RPC message
    result = handle_rpc(msg)
    
    # Route response back through the SSE stream
    qs = parse_qs(request.query_string)
    session_id = qs.get("session_id", [""])[0]
    if session_id and session_id in request.app["mcp_sessions"]:
        stream = request.app["mcp_sessions"][session_id].get("stream")
        if stream and result is not None:
            try:
                payload = json.dumps(result, ensure_ascii=False)
                await stream.write(f"event: message\ndata: {payload}\n\n".encode())
            except (ConnectionResetError, ConnectionError):
                pass
    
    return web.Response(status=202)


# ============================================================================
# HANDLER — MCP WebSocket
# ============================================================================

async def handle_ws(request: web.Request) -> web.WebSocketResponse:
    """WebSocket MCP transport — full-duplex JSON-RPC."""
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
    r = require_auth(request)
    if r: return r
    return web.json_response({
        "ok": True, "service": "arena-web-gateway", "version": "1.0.0",
        "endpoints": ["/gateway", "/gateway/tools", "/run (POST)", "/tool (POST)"],
        "mcp_proxy": "/mcp",
        "auth_required": True,
    })


async def handle_gateway_tools(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    mcp_tools = handle_rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    return web.json_response({
        "ok": True,
        "whitelist_prefixes": list(GW_WHITELIST),
        "mcp_tools": mcp_tools.get("result", {}).get("tools", []) if mcp_tools else [],
    })


async def handle_gateway_run(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad json"}, status=400)
    cmd = (data.get("command") or "").strip()
    if not cmd:
        return web.json_response({"ok": False, "error": "missing command"}, status=400)
    if not gw_allowed(cmd):
        return web.json_response({"ok": False, "error": "command not in whitelist",
                                   "allowed": list(GW_WHITELIST)}, status=403)
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=int(data.get("timeout", 60)))
        return web.json_response({"ok": p.returncode == 0, "exit": p.returncode,
                                   "stdout": p.stdout[-20000:], "stderr": p.stderr[-3000:]})
    except subprocess.TimeoutExpired:
        return web.json_response({"ok": False, "exit": -1, "stdout": "", "stderr": "timeout"})
    except Exception as e:
        return web.json_response({"ok": False, "exit": -2, "stdout": "", "stderr": str(e)})


async def handle_gateway_tool(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad json"}, status=400)
    name = data.get("name")
    args = data.get("arguments") or {}
    if not name:
        return web.json_response({"ok": False, "error": "missing tool name"}, status=400)
    resp = handle_rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": name, "arguments": args}})
    return web.json_response({"ok": "error" not in (resp or {}), "response": resp})


# ============================================================================
# MAIN
# ============================================================================

def serve(args: argparse.Namespace) -> None:
    token = args.token or os.environ.get("ARENA_LOCAL_BRIDGE_TOKEN")
    if not token:
        print("No token provided. Use --token or set ARENA_LOCAL_BRIDGE_TOKEN.", file=sys.stderr)
        raise SystemExit(2)

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
        "semaphore": asyncio.Semaphore(args.max_concurrent),
        "active_exec": 0,
    }

    app = make_app(cfg)

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
    sp.add_argument("--bind", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8765)
    sp.add_argument("--token")
    sp.add_argument("--root", default=str(Path.home()))
    sp.add_argument("--allow-any-cwd", action="store_true")
    sp.add_argument("--profile", choices=["cautious", "owner-shell"], default="cautious")
    sp.add_argument("--timeout", type=int, default=60)
    sp.add_argument("--max-timeout", type=int, default=600)
    sp.add_argument("--max-output", type=int, default=DEFAULT_MAX_OUTPUT)
    sp.add_argument("--max-concurrent", type=int, default=DEFAULT_MAX_CONCURRENT)
    sp.set_defaults(func=serve)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
