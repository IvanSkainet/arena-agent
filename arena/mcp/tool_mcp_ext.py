"""MCP tools for using EXTERNAL MCP servers through the bridge (v4.94.0).

The bridge exposes its own tools; these tools let the agent also use
*external* MCP servers registered in ``mcp/mcp.json`` (Desktop-Commander,
ScreenPilot, the official filesystem/fetch/git servers, ...) by connecting
to them with the MCP client (``arena.mcp_client``) and calling their tools.

* ``mcp.ext_servers``            -- list registered servers + running status.
* ``mcp.ext_tools(server)``      -- connect and list a server's tools.
* ``mcp.ext_call(server,tool,..)``-- call a tool on an external server.
* ``mcp.ext_stop(server)``       -- stop a running server (lifecycle).
"""
from __future__ import annotations

import json
from typing import Any

from arena.mcp.tool_utils import text_content
from arena.mcp_client import McpError, get_manager


def _result(payload: dict[str, Any]) -> dict[str, Any]:
    return text_content(json.dumps(payload, ensure_ascii=False))


def _ext_add(args: dict[str, Any]) -> dict[str, Any]:
    """Register an external MCP server in mcp/mcp.json (the trust decision).

    Two ways:
      * explicit: pass ``command`` (+ ``args``/``env``) to register ANY MCP
        server, e.g. {"name":"desktop-commander","command":"npx",
        "args":["-y","@wonderwhy-er/desktop-commander"]}.
      * by name: pass only ``name`` to install from the marketplace registry
        (handles git-venv servers like screenpilot too: clone + venv + pip).
    """
    from arena.mcp_marketplace.commands import _install_git_venv
    from arena.mcp_marketplace.registry import _load_config, _load_registry, _save_config

    name = str(args.get("name", "") or "").strip()
    if not name:
        return {"ok": False, "error": "missing 'name' argument"}
    command = str(args.get("command", "") or "").strip()

    if command:
        server_args = args.get("args") or []
        env = args.get("env") or {}
        if not isinstance(server_args, list) or not isinstance(env, dict):
            return {"ok": False, "error": "'args' must be a list and 'env' an object"}
        cfg = _load_config()
        cfg.setdefault("mcpServers", {})[name] = {
            "command": command, "args": server_args, "env": env,
        }
        _save_config(cfg)
        return {"ok": True, "added": name, "command": command,
                "args": server_args, "source": "explicit"}

    # by name -> marketplace registry
    reg = _load_registry()
    if name not in reg:
        return {"ok": False, "error": (
            f"'{name}' is not in the marketplace registry; pass an explicit "
            f"'command' (+ 'args') to register an arbitrary MCP server.")}
    meta = reg[name]
    if meta.get("type") == "git-venv":
        rc = _install_git_venv(name, meta)
        return {"ok": rc == 0, "added": name if rc == 0 else None,
                "source": "registry(git-venv)"}
    cfg = _load_config()
    cfg.setdefault("mcpServers", {})[name] = {
        "command": meta["command"], "args": meta.get("args", []),
        "env": meta.get("env", {}),
    }
    _save_config(cfg)
    return {"ok": True, "added": name, "command": meta["command"],
            "args": meta.get("args", []), "source": "registry"}


def _ext_remove(args: dict[str, Any]) -> dict[str, Any]:
    from arena.mcp_marketplace.registry import _load_config, _save_config
    name = str(args.get("name", "") or "").strip()
    if not name:
        return {"ok": False, "error": "missing 'name' argument"}
    cfg = _load_config()
    servers = cfg.get("mcpServers", {})
    if name not in servers:
        return {"ok": False, "error": f"'{name}' is not registered"}
    del servers[name]
    _save_config(cfg)
    get_manager().stop(name)  # stop a running instance, if any
    return {"ok": True, "removed": name}


def _ext_servers(args: dict[str, Any]) -> dict[str, Any]:
    mgr = get_manager()
    servers = mgr.servers()
    out = []
    for name, cfg in sorted(servers.items()):
        st = mgr.status(name)
        out.append({
            "name": name,
            "command": cfg.get("command", ""),
            "args": cfg.get("args", []),
            "running": st["running"],
        })
    return {"ok": True, "count": len(out), "servers": out}


def _ext_tools(args: dict[str, Any]) -> dict[str, Any]:
    server = str(args.get("server", "") or "").strip()
    if not server:
        return {"ok": False, "error": "missing 'server' argument"}
    refresh = bool(args.get("refresh", False))
    try:
        tools = get_manager().list_tools(server, refresh=refresh)
    except McpError as e:
        return {"ok": False, "error": str(e)}
    slim = [{"name": t.get("name", ""),
             "description": t.get("description", "")} for t in tools]
    return {"ok": True, "server": server, "count": len(slim), "tools": slim}


def _ext_call(args: dict[str, Any]) -> dict[str, Any]:
    server = str(args.get("server", "") or "").strip()
    tool = str(args.get("tool", "") or "").strip()
    if not server or not tool:
        return {"ok": False, "error": "missing 'server' and/or 'tool' argument"}
    arguments = args.get("arguments") or args.get("args") or {}
    if not isinstance(arguments, dict):
        return {"ok": False, "error": "'arguments' must be an object"}
    timeout = args.get("timeout", 60)
    try:
        timeout_f = max(1.0, min(float(timeout), 180.0))
    except (TypeError, ValueError):
        return {"ok": False, "error": "'timeout' must be a number of seconds"}
    try:
        res = get_manager().call_tool(server, tool, arguments, timeout=timeout_f)
    except McpError as e:
        return {"ok": False, "error": str(e), "server": server, "tool": tool}
    res["server"] = server
    res["tool"] = tool
    return res


def _ext_stop(args: dict[str, Any]) -> dict[str, Any]:
    server = str(args.get("server", "") or "").strip()
    if not server:
        return {"ok": False, "error": "missing 'server' argument"}
    get_manager().stop(server)
    return {"ok": True, "server": server, "stopped": True}


def handle_mcp_ext_tool(name: str, args: dict[str, Any], *, ctx=None) -> dict[str, Any] | None:
    if name == "mcp.ext_servers":
        return _result(_ext_servers(args))
    if name == "mcp.ext_tools":
        return _result(_ext_tools(args))
    if name == "mcp.ext_call":
        return _result(_ext_call(args))
    if name == "mcp.ext_stop":
        return _result(_ext_stop(args))
    if name == "mcp.add":
        return _result(_ext_add(args))
    if name == "mcp.remove":
        return _result(_ext_remove(args))
    return None


__all__ = ["handle_mcp_ext_tool"]
