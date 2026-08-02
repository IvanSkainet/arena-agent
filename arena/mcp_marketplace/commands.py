"""MCP marketplace commands."""
from __future__ import annotations

import json
import os
import subprocess
import sys

from arena.mcp_marketplace.registry import MCP_DIR, _load_config, _load_registry, _save_config


def cmd_registry(_args):
    reg = _load_registry()
    items = []
    for name, meta in sorted(reg.items()):
        items.append({"name": name, "description": meta.get("description", ""),
                      "command": meta.get("command", ""),
                      "tags": meta.get("tags", [])})
    print(json.dumps(items, ensure_ascii=False, indent=2))
    return 0

def _install_git_venv(name: str, meta: dict) -> int:
    """Install a git+venv MCP server (v4.94.0): clone the repo into
    mcp/servers/<name>, create a venv, install its requirements, then
    register the venv interpreter + entry script in mcp.json.

    Idempotent: skips clone/venv steps that already exist so re-running
    only tops up the registration."""
    servers_dir = MCP_DIR / "servers"
    servers_dir.mkdir(parents=True, exist_ok=True)
    dest = servers_dir / name
    if not (dest / ".git").exists():
        print(f"[INFO] cloning {meta.get('repo')} -> {dest} ...")
        r = subprocess.run(["git", "clone", "--depth", "1", meta["repo"], str(dest)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(f"ERR: git clone failed: {r.stderr[-300:]}", file=sys.stderr)
            return 1
    venv_dir = dest / "venv"
    venv_python = (venv_dir / "Scripts" / "python.exe") if os.name == "nt" \
        else (venv_dir / "bin" / "python")
    if not venv_python.exists():
        print(f"[INFO] creating venv at {venv_dir} ...")
        r = subprocess.run([sys.executable, "-m", "venv", str(venv_dir)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(f"ERR: venv create failed: {r.stderr[-300:]}", file=sys.stderr)
            return 1
    req = dest / meta.get("requirements", "requirements.txt")
    if req.exists():
        print(f"[INFO] installing requirements ({req.name}) into venv ...")
        r = subprocess.run([str(venv_python), "-m", "pip", "install", "-q",
                            "-r", str(req)], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"WARN: pip install reported issues: {r.stderr[-300:]}",
                  file=sys.stderr)
    entry = dest / meta.get("entry", "main.py")
    cfg = _load_config()
    cfg.setdefault("mcpServers", {})[name] = {
        "command": str(venv_python),
        "args":    [str(entry)],
        "env":     meta.get("env", {}),
    }
    _save_config(cfg)
    print(f"installed: {name} (git-venv)")
    print(f"  python: {venv_python}")
    print(f"  entry:  {entry}")
    print(f"  desc:   {meta.get('description','')}")
    return 0


def cmd_install(args):
    reg = _load_registry()
    if args.name not in reg:
        print(f"ERR: '{args.name}' not in registry", file=sys.stderr)
        return 1
    meta = reg[args.name]
    # v4.94.0: git+venv servers need a clone+venv setup before they can run.
    if meta.get("type") == "git-venv":
        return _install_git_venv(args.name, meta)
    cfg = _load_config()
    cfg.setdefault("mcpServers", {})[args.name] = {
        "command": meta["command"],
        "args":    meta.get("args", []),
        "env":     meta.get("env", {}),
    }
    _save_config(cfg)
    print(f"installed: {args.name}")
    print(f"  command: {meta['command']} {' '.join(meta.get('args', []))}")
    print(f"  desc:    {meta.get('description','')}")
    return 0

def cmd_remove(args):
    cfg = _load_config()
    if args.name not in cfg.get("mcpServers", {}):
        print(f"not installed: {args.name}", file=sys.stderr)
        return 1
    del cfg["mcpServers"][args.name]
    _save_config(cfg)
    print(f"removed: {args.name}")
    return 0

def cmd_list(_args):
    print(json.dumps(_load_config(), ensure_ascii=False, indent=2))
    return 0

def cmd_test(args):
    cfg = _load_config()
    srv = cfg.get("mcpServers", {}).get(args.name)
    if not srv:
        print(f"not installed: {args.name}", file=sys.stderr)
        return 1
    if srv["command"] not in ("npx", "uvx", "python", "python3", "node", "echo"):
        print(f"refusing unknown command: {srv['command']}", file=sys.stderr)
        return 2

    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                       "clientInfo": {"name": "arena-mcp-test", "version": "0.1"}}}
    notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    tools = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    msg = json.dumps(init) + "\n" + json.dumps(notif) + "\n" + json.dumps(tools) + "\n"

    try:
        p = subprocess.run([srv["command"]] + srv.get("args", []),
                            input=msg, capture_output=True, text=True, timeout=30,
                            env={**os.environ, **srv.get("env", {})})
        lines = [line for line in p.stdout.splitlines() if line.strip().startswith("{")]
        results = []
        for line in lines:
            try:
                results.append(json.loads(line))
            except Exception:
                pass
        print(json.dumps({"ok": p.returncode == 0, "name": args.name,
                          "responses_count": len(results),
                          "first_response": results[0] if results else None,
                          "tools_count": len((results[-1].get("result", {}).get("tools", []) if results and "tools" in str(results[-1]) else [])),
                          "stderr_tail": p.stderr[-400:]}, ensure_ascii=False, indent=2))
        return 0 if p.returncode == 0 else 1
    except FileNotFoundError:
        print(json.dumps({"ok": False, "error": f"command not found: {srv['command']} (install npx/uvx)"}, indent=2))
        return 2
    except subprocess.TimeoutExpired:
        print(json.dumps({"ok": False, "error": "timeout 30s"}, indent=2))
        return 3
