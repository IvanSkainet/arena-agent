"""MCP marketplace commands."""
from __future__ import annotations

import json
import os
import subprocess
import sys

from arena.mcp_marketplace.registry import _load_config, _load_registry, _save_config

def cmd_registry(_args):
    reg = _load_registry()
    items = []
    for name, meta in sorted(reg.items()):
        items.append({"name": name, "description": meta.get("description", ""),
                      "command": meta.get("command", ""),
                      "tags": meta.get("tags", [])})
    print(json.dumps(items, ensure_ascii=False, indent=2))
    return 0

def cmd_install(args):
    reg = _load_registry()
    if args.name not in reg:
        print(f"ERR: '{args.name}' not in registry", file=sys.stderr)
        return 1
    cfg = _load_config()
    cfg.setdefault("mcpServers", {})[args.name] = {
        "command": reg[args.name]["command"],
        "args":    reg[args.name].get("args", []),
        "env":     reg[args.name].get("env", {}),
    }
    _save_config(cfg)
    print(f"installed: {args.name}")
    print(f"  command: {reg[args.name]['command']} {' '.join(reg[args.name].get('args', []))}")
    print(f"  desc:    {reg[args.name].get('description','')}")
    return 0

def cmd_remove(args):
    cfg = _load_config()
    if args.name not in cfg.get("mcpServers", {}):
        print(f"not installed: {args.name}", file=sys.stderr); return 1
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
        print(f"not installed: {args.name}", file=sys.stderr); return 1
    if srv["command"] not in ("npx", "uvx", "python", "python3", "node", "echo"):
        print(f"refusing unknown command: {srv['command']}", file=sys.stderr); return 2

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
        lines = [l for l in p.stdout.splitlines() if l.strip().startswith("{")]
        results = []
        for l in lines:
            try: results.append(json.loads(l))
            except Exception: pass
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
