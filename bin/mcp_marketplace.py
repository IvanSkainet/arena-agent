#!/usr/bin/env python3
"""mcp_marketplace.py — реестр и установщик MCP-серверов.

Идея (от MCP-SuperAssistant + Claude Code plugins): curated registry популярных
MCP-серверов, чтобы одной командой добавить их в ~/arena-bridge/mcp/mcp.json
и сразу попробовать.

Команды:
  registry              — показать каталог
  install <name>        — добавить запись в mcp.json
  remove  <name>        — убрать
  list                  — текущие mcpServers
  test    <name>        — попробовать запустить stdio + initialize + tools/list
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys
from pathlib import Path

ROOT = Path(os.environ.get("ARENA_AGENT_HOME", str(Path.home() / "arena-bridge"))).expanduser()
MCP_DIR = ROOT / "mcp"
CONFIG = MCP_DIR / "mcp.json"
REGISTRY = MCP_DIR / "registry.json"

DEFAULT_REGISTRY = {
    "filesystem": {
        "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", str(Path.home())],
        "description": "File system access (read/write/list) inside given root.",
        "tags": ["fs", "official"],
    },
    "fetch": {
        "command": "uvx", "args": ["-q", "mcp-server-fetch"],
        "description": "HTTP fetch tool (server-side).",
        "tags": ["web", "official"],
    },
    "sqlite": {
        "command": "uvx", "args": ["-q", "mcp-server-sqlite", "--db-path", str(ROOT / "memory" / "facts.db")],
        "description": "SQLite query tool over local DB.",
        "tags": ["db", "official"],
    },
    "git": {
        "command": "uvx", "args": ["-q", "mcp-server-git", "--repository", str(Path.home())],
        "description": "Git operations (status, log, diff, branch).",
        "tags": ["git", "official"],
    },
    "memory": {
        "command": "npx", "args": ["-y", "@modelcontextprotocol/server-memory"],
        "description": "Knowledge-graph long-term memory.",
        "tags": ["memory", "official"],
    },
    "time": {
        "command": "uvx", "args": ["-q", "mcp-server-time"],
        "description": "Time, timezones, date math.",
        "tags": ["util", "official"],
    },
    "puppeteer": {
        "command": "npx", "args": ["-y", "@modelcontextprotocol/server-puppeteer"],
        "description": "Browser automation via Puppeteer (chromium needed).",
        "tags": ["browser"],
    },
    "everything": {
        "command": "npx", "args": ["-y", "@modelcontextprotocol/server-everything"],
        "description": "Reference server with all MCP feature types.",
        "tags": ["test", "official"],
    },
    "arena-stream": {
        "command": "echo", "args": ["arena-mcp-stream runs on http://127.0.0.1:8767/mcp"],
        "description": "Local arena-mcp-stream service (20 tools).",
        "tags": ["local", "arena"],
    },
}


def _ensure():
    MCP_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG.exists():
        CONFIG.write_text(json.dumps({"mcpServers": {}}, indent=2))
    if not REGISTRY.exists():
        REGISTRY.write_text(json.dumps(DEFAULT_REGISTRY, ensure_ascii=False, indent=2))


def _load_registry():
    _ensure()
    try: return json.loads(REGISTRY.read_text())
    except Exception: return dict(DEFAULT_REGISTRY)


def _load_config():
    _ensure()
    try: return json.loads(CONFIG.read_text())
    except Exception: return {"mcpServers": {}}


def _save_config(cfg):
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))


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


def main():
    ap = argparse.ArgumentParser(prog="mcp_marketplace")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("registry").set_defaults(func=cmd_registry)
    s = sub.add_parser("install"); s.add_argument("name"); s.set_defaults(func=cmd_install)
    s = sub.add_parser("remove");  s.add_argument("name"); s.set_defaults(func=cmd_remove)
    sub.add_parser("list").set_defaults(func=cmd_list)
    s = sub.add_parser("test"); s.add_argument("name"); s.set_defaults(func=cmd_test)
    args = ap.parse_args()
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
