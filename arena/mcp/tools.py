"""MCP tool registry and JSON-RPC dispatcher."""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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





@dataclass(frozen=True)
class McpToolContext:
    version: str
    bin_dir: Any
    bridge_dir: Any
    reports_dir: Any
    subprocess_kwargs: Callable[[], dict[str, Any]]
    blocked_reason: Callable[[str], str | None]
    first_word: Callable[[str], str]
    cautious_allow: set[str]
    under_root: Callable[[Path, Path], bool]
    write_fact: Callable[[dict[str, Any]], None]
    load_facts: Callable[[], list[dict[str, Any]]]
    audit: Callable[[dict[str, Any]], None]
    app_config: Callable[[], dict[str, Any]]
    common_status: Callable[[dict[str, Any]], dict[str, Any]]
    skills_list_sync_with_cache: Callable[[], dict[str, Any]]
    skills_run_sync: Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class McpToolRuntime:
    tools: list[dict[str, Any]]
    run_local: Callable[..., tuple[int, str, str]]
    run_sd: Callable[..., tuple[int, str, str]]
    text_content: Callable[[str], dict[str, Any]]
    call_tool: Callable[[str, dict[str, Any]], dict[str, Any]]
    handle_rpc: Callable[[dict[str, Any]], dict[str, Any] | None]


def make_mcp_tool_runtime(ctx: McpToolContext) -> McpToolRuntime:
    def run_local(argv: list[str], timeout: int = 30) -> tuple[int, str, str]:
        """Run a command directly (no GUI/sandbox needed)."""
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, **ctx.subprocess_kwargs())
        return p.returncode, p.stdout, p.stderr


    def run_sd(argv: list[str], timeout: int = 60) -> tuple[int, str, str]:
        """Run command via sd-exec (Linux) or directly (Windows)."""
        if platform.system() == "Windows":
            p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, shell=True, **ctx.subprocess_kwargs())
            return p.returncode, p.stdout, p.stderr
        else:
            sd = os.path.join(ctx.bin_dir, "sd-exec")
            p = subprocess.run([sd, "--timeout", str(timeout), "--"] + argv,
                               capture_output=True, text=True, timeout=timeout + 10, **ctx.subprocess_kwargs())
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
                # Security: check blocked patterns (same as /v1/exec)
                block = ctx.blocked_reason(cmd)
                if block:
                    return {"isError": True, "content": [{"type": "text", "text": f"BLOCKED: {block}"}]}
                # Security: check profile allowlist (only for cautious profile)
                profile = os.environ.get("ARENA_PROFILE", "owner-shell")
                if profile == "cautious":
                    fw = ctx.first_word(cmd)
                    if ctx.cautious_allow and fw not in ctx.cautious_allow and fw.rstrip(".exe") not in ctx.cautious_allow:
                        return {"isError": True, "content": [{"type": "text", "text": f"BLOCKED: command '{fw}' not in allowlist"}]}
                if platform.system() == "Windows":
                    rc, out, err = run_sd(["cmd", "/c", cmd], timeout=args.get("timeout", 60))
                else:
                    rc, out, err = run_sd(["bash", "-lc", cmd], timeout=args.get("timeout", 60))
                return text_content(json.dumps({"exit": rc, "stdout": out[-15000:], "stderr": err[-5000:]}, ensure_ascii=False))
            # Sensitive files that must never be read via MCP
            _MCP_BLOCKED_FILES = {"token.txt", "users.json", ".env", "id_rsa", "id_ed25519",
                                   "id_ecdsa", "id_dsa", ".netrc", ".ssh_config"}

            if name == "fs.read":
                p = os.path.expanduser(args.get("path", ""))
                if not p:
                    return {"isError": True, "content": [{"type": "text", "text": "ERROR: missing 'path' argument"}]}
                # Security: block reading sensitive files
                if Path(p).name in _MCP_BLOCKED_FILES:
                    return {"isError": True, "content": [{"type": "text", "text": f"BLOCKED: reading {Path(p).name} is not allowed"}]}
                # Security: restrict to home directory
                resolved = Path(p).resolve()
                home = Path.home().resolve()
                if not ctx.under_root(resolved, home):
                    return {"isError": True, "content": [{"type": "text", "text": "BLOCKED: path outside home directory"}]}
                try:
                    with open(p, "rb") as f:
                        data = f.read(args.get("max_bytes", 200000))
                    return text_content(data.decode("utf-8", "replace"))
                except PermissionError:
                    return {"isError": True, "content": [{"type": "text", "text": "ERROR: permission denied"}]}
                except FileNotFoundError:
                    return {"isError": True, "content": [{"type": "text", "text": "ERROR: file not found"}]}
            if name == "fs.write":
                p = os.path.expanduser(args.get("path", ""))
                content = args.get("content", "")
                if not p:
                    return {"isError": True, "content": [{"type": "text", "text": "ERROR: missing 'path' argument"}]}
                # Security: block writing sensitive files
                if Path(p).name in _MCP_BLOCKED_FILES:
                    return {"isError": True, "content": [{"type": "text", "text": f"BLOCKED: writing {Path(p).name} is not allowed"}]}
                # Security: restrict to home directory
                resolved = Path(p).resolve()
                home = Path.home().resolve()
                if not ctx.under_root(resolved, home):
                    return {"isError": True, "content": [{"type": "text", "text": "BLOCKED: path outside home directory"}]}
                try:
                    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
                    with open(p, "w", encoding="utf-8") as f:
                        f.write(content)
                    return text_content(f"wrote {len(content)} bytes to {p}")
                except PermissionError:
                    return {"isError": True, "content": [{"type": "text", "text": "ERROR: permission denied"}]}
            if name == "fs.list":
                p = os.path.expanduser(args.get("path", ""))
                if not p:
                    return {"isError": True, "content": [{"type": "text", "text": "ERROR: missing 'path' argument"}]}
                # Security: restrict to home directory
                resolved = Path(p).resolve()
                home = Path.home().resolve()
                if not ctx.under_root(resolved, home):
                    return {"isError": True, "content": [{"type": "text", "text": "BLOCKED: path outside home directory"}]}
                try:
                    return text_content(json.dumps(sorted(os.listdir(p))))
                except PermissionError:
                    return {"isError": True, "content": [{"type": "text", "text": "ERROR: permission denied"}]}
                except FileNotFoundError:
                    return {"isError": True, "content": [{"type": "text", "text": "ERROR: directory not found"}]}
            if name == "browser.search":
                rc, out, err = run_local([sys.executable, os.path.join(ctx.bin_dir, "py_browser.py"),
                                           "search", args.get("query", ""), "--n", str(args.get("n", 5))], timeout=30)
                return text_content(out or err)
            if name == "browser.read":
                rc, out, err = run_local([sys.executable, os.path.join(ctx.bin_dir, "py_browser.py"),
                                           "read", args.get("url", "")], timeout=30)
                return text_content(out or err)
            if name == "browser.shot":
                import shutil as _shutil
                shots = str(ctx.reports_dir / "shots")
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
                key = args.get("key", "")
                value = args.get("value", "")
                if not key:
                    return {"isError": True, "content": [{"type": "text", "text": "ERROR: missing 'key' argument"}]}
                tags = args.get("tags") or []
                entry = {"key": key, "value": value, "tags": tags,
                         "timestamp": datetime.now(timezone.utc).isoformat()}
                ctx.write_fact(entry)
                ctx.audit({"type": "memory_set", "key": key, "via": "mcp"})
                return text_content(json.dumps({"ok": True, "fact": entry}, ensure_ascii=False))
            if name == "mem.get":
                q = args.get("query", args.get("q", ""))
                facts = ctx.load_facts()
                if q:
                    import fnmatch as _fn
                    q_low = q.lower()
                    scored = []
                    for f in facts:
                        if q_low in json.dumps(f, ensure_ascii=False).lower():
                            scored.append(f)
                    facts = scored
                return text_content(json.dumps({"ok": True, "count": len(facts), "facts": facts[-50:]}, ensure_ascii=False))
            if name == "sys.status":
                cfg = ctx.app_config()
                return text_content(json.dumps(ctx.common_status(cfg), ensure_ascii=False))
            if name == "skill.list":
                result = ctx.skills_list_sync_with_cache()
                skills = result.get("skills", [])
                return text_content(json.dumps({"ok": True, "count": len(skills), "skills": skills}, ensure_ascii=False))
            if name == "skill.run":
                sk = args.get("name", "")
                extra = args.get("args") or []
                result = ctx.skills_run_sync(sk, list(extra))
                return text_content(json.dumps(result, ensure_ascii=False))
            if name == "hooks.list":
                hooks_dir = ctx.bridge_dir / "hooks"
                pre_dir = hooks_dir / "pre_skill.d"
                post_dir = hooks_dir / "post_skill.d"
                hooks = []
                for d, phase in [(pre_dir, "pre"), (post_dir, "post")]:
                    if d.exists():
                        for f in sorted(d.iterdir()):
                            if f.is_file():
                                hooks.append({"phase": phase, "name": f.name, "path": str(f)})
                return text_content(json.dumps({"ok": True, "count": len(hooks), "hooks": hooks}, ensure_ascii=False))
            if name == "snapshot":
                result = ctx.skills_run_sync("system/sys-snapshot", [])
                return text_content(json.dumps(result, ensure_ascii=False))
            if name == "subagent.spawn":
                cmd_args = [sys.executable, os.path.join(ctx.bin_dir, "subagent.py"), "spawn", args.get("cmd", "")]
                if args.get("name"):
                    cmd_args += ["--name", args["name"]]
                if args.get("wait", True):
                    cmd_args += ["--wait"]
                cmd_args += ["--timeout", str(args.get("timeout", 300))]
                rc, out, err = run_local(cmd_args, timeout=args.get("timeout", 300) + 30)
                return text_content(out or err)
            if name == "subagent.list":
                rc, out, err = run_local([sys.executable, os.path.join(ctx.bin_dir, "subagent.py"), "list"], timeout=10)
                return text_content(out or err)
            if name == "memory.recall":
                cmd_args = [sys.executable, os.path.join(ctx.bin_dir, "memory_recall.py"), "recall",
                            args.get("query", ""), "--top", str(args.get("top", 5))]
                rc, out, err = run_local(cmd_args, timeout=15)
                return text_content(out or err)
            if name == "memory.digest":
                rc, out, err = run_local([sys.executable, os.path.join(ctx.bin_dir, "memory_recall.py"), "digest"], timeout=15)
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
                "serverInfo": {"name": "arena-unified-bridge", "version": ctx.version},
                "capabilities": {"tools": {"listChanged": False}}}}
        if m == "tools/list":
            return {"jsonrpc": "2.0", "id": rid, "result": {"tools": MCP_TOOLS}}
        if m == "tools/call":
            params = msg.get("params") or {}
            return {"jsonrpc": "2.0", "id": rid, "result": call_tool(params.get("name", ""), params.get("arguments") or {})}
        if m == "notifications/initialized":
            return None
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"Method not found: {m}"}}

    return McpToolRuntime(
        tools=MCP_TOOLS,
        run_local=run_local,
        run_sd=run_sd,
        text_content=text_content,
        call_tool=call_tool,
        handle_rpc=handle_rpc,
    )
