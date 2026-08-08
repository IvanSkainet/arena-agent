"""MCP Server Foundry: author, test, and install external MCP servers."""
from __future__ import annotations

import base64
import json
import os
import shutil
from pathlib import Path
from typing import Any

from arena.jsonshape import loads_object
from arena.mcp_client.client import McpError, McpStdioClient


def root() -> Path:
    p = Path(os.environ.get("ARENA_AGENT_HOME", str(Path.home() / "arena-bridge"))).expanduser() / "mcp-servers"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _safe_name(name: str) -> str:
    n = str(name or "").strip()
    if not n or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in n) or n in {".", ".."}:
        raise ValueError("server name must use only letters, digits, dot, underscore and dash")
    return n[:80]


def _server_dir(name: str) -> Path:
    return root() / _safe_name(name)


def _safe_rel(path: str) -> Path:
    rel = Path(str(path).replace("\\", "/"))
    if not str(path).strip() or rel.is_absolute() or rel.drive or any(part in ("..", "") for part in rel.parts):
        raise ValueError(f"unsafe server path: {path!r}")
    return rel


def _default_server_py() -> str:
    return r'''
import json, sys, time
TOOLS = [{
    "name": "echo",
    "description": "Echo text back with an MCP Server Foundry marker.",
    "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"], "additionalProperties": False},
}]

def reply(rid, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": rid}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result or {}
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()

for line in sys.stdin:
    try:
        req = json.loads(line)
        rid = req.get("id")
        method = req.get("method")
        params = req.get("params") or {}
        if method == "initialize":
            reply(rid, {"protocolVersion": "2025-03-26", "serverInfo": {"name": "arena-foundry-echo", "version": "1.0.0"}, "capabilities": {"tools": {}}})
        elif method == "tools/list":
            reply(rid, {"tools": TOOLS})
        elif method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            if name == "echo":
                text = str(args.get("text", ""))
                reply(rid, {"content": [{"type": "text", "text": json.dumps({"ok": True, "marker": "MCP_SERVER_FOUNDRY_PROOF", "text": text}, ensure_ascii=False)}]})
            else:
                reply(rid, {"isError": True, "content": [{"type": "text", "text": "unknown tool"}]})
        elif rid is not None:
            reply(rid, error={"code": -32601, "message": "method not found"})
    except Exception as e:
        try:
            reply(req.get("id") if isinstance(req, dict) else None, error={"code": -32000, "message": str(e)})
        except Exception:
            pass
'''.lstrip()


def _write_file(base: Path, item: dict[str, Any]) -> str:
    rel = _safe_rel(str(item.get("path") or ""))
    target = base / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    content = item.get("content", "")
    enc = str(item.get("encoding") or "utf-8").lower()
    if enc == "base64":
        target.write_bytes(base64.b64decode(str(content)))
    else:
        target.write_text(str(content), encoding="utf-8")
    return rel.as_posix()


def _meta_path(name: str) -> Path:
    return _server_dir(name) / ".arena-mcp-server.json"


def create(name: str, *, files: list[dict[str, Any]] | None = None,
           command: str | None = None, args: list[str] | None = None,
           entry: str = "server.py", overwrite: bool = False) -> dict[str, Any]:
    safe = _safe_name(name)
    d = _server_dir(safe)
    if d.exists() and not overwrite:
        return {"ok": False, "error": "server project already exists", "server": safe}
    if d.exists() and overwrite:
        shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)
    written = []
    if files:
        for item in files:
            if not isinstance(item, dict):
                return {"ok": False, "error": "files entries must be objects"}
            written.append(_write_file(d, item))
    else:
        (d / entry).write_text(_default_server_py(), encoding="utf-8")
        written.append(entry)
    cmd = command or ("python" if os.name == "nt" else "python3")
    server_args = args if isinstance(args, list) else [entry]
    meta = {"name": safe, "command": str(cmd), "args": [str(a) for a in server_args], "cwd": str(d), "files": written}
    _meta_path(safe).write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "server": safe, "path": str(d), "config": meta}


def _load_meta(name: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        data = json.loads(_meta_path(name).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "server project not found"
    except Exception as e:
        return None, f"invalid server metadata: {e}"
    return data if isinstance(data, dict) else None, None


def list_servers() -> dict[str, Any]:
    rows = []
    for d in sorted(root().iterdir()):
        if not d.is_dir():
            continue
        meta, err = _load_meta(d.name)
        rows.append({"server": d.name, "path": str(d), "config": meta, "error": err})
    return {"ok": True, "count": len(rows), "servers": rows}


def test(name: str, *, tool: str | None = None, arguments: dict[str, Any] | None = None,
         timeout: float = 15) -> dict[str, Any]:
    meta, err = _load_meta(name)
    if err or not meta:
        return {"ok": False, "error": err or "server metadata missing"}
    client = McpStdioClient(str(meta.get("command") or ""), list(meta.get("args") or []), cwd=str(meta.get("cwd") or ""))
    try:
        info = client.start(timeout=timeout)
        tools = client.list_tools(timeout=timeout, refresh=True)
        out: dict[str, Any] = {"ok": True, "server": _safe_name(name), "server_info": info, "tool_count": len(tools), "tools": [{"name": t.get("name"), "description": t.get("description", "")} for t in tools]}
        if tool:
            out["call"] = client.call_tool(tool, arguments or {}, timeout=timeout)
            out["ok"] = bool(out["call"].get("ok"))
        return out
    except McpError as e:
        return {"ok": False, "server": _safe_name(name), "error": str(e)}
    finally:
        client.stop()


def _mcp_config_path() -> Path:
    p = Path(os.environ.get("ARENA_AGENT_HOME", str(Path.home() / "arena-bridge"))).expanduser() / "mcp" / "mcp.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text(json.dumps({"mcpServers": {}}, indent=2), encoding="utf-8")
    return p


def _load_mcp_config() -> dict[str, Any]:
    try:
        return loads_object(_mcp_config_path().read_text(encoding="utf-8"),
                            default={"mcpServers": {}})
    except Exception:
        return {"mcpServers": {}}


def _save_mcp_config(cfg: dict[str, Any]) -> None:
    _mcp_config_path().write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def install(name: str, *, force: bool = False, test_tool: str | None = None,
            test_arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    checked = test(name, tool=test_tool, arguments=test_arguments or ({"text": "install-proof"} if test_tool else None))
    if not checked.get("ok"):
        return {"ok": False, "error": "server test failed; not installed", "test": checked}
    meta, err = _load_meta(name)
    if err or not meta:
        return {"ok": False, "error": err or "server metadata missing"}
    cfg = _load_mcp_config()
    servers = cfg.setdefault("mcpServers", {})
    server_name = _safe_name(name)
    if server_name in servers and not force:
        return {"ok": False, "error": "server already installed; set force=true", "server": server_name}
    servers[server_name] = {"command": meta["command"], "args": meta.get("args", []), "cwd": meta.get("cwd"), "env": meta.get("env", {})}
    _save_mcp_config(cfg)
    return {"ok": True, "server": server_name, "installed": servers[server_name], "test": checked}
