"""MCP filesystem tools."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from arena.mcp.tool_utils import text_content

_MCP_BLOCKED_FILES = {
    "token.txt", "users.json", ".env", "id_rsa", "id_ed25519",
    "id_ecdsa", "id_dsa", ".netrc", ".ssh_config",
}


def _validate_home_path(path: str, ctx) -> tuple[Path | None, dict[str, Any] | None]:
    if not path:
        return None, {"isError": True, "content": [{"type": "text", "text": "ERROR: missing 'path' argument"}]}
    if Path(path).name in _MCP_BLOCKED_FILES:
        action = "reading" if not Path(path).exists() or Path(path).is_file() else "accessing"
        return None, {"isError": True, "content": [{"type": "text", "text": f"BLOCKED: {action} {Path(path).name} is not allowed"}]}
    resolved = Path(path).resolve()
    home = Path.home().resolve()
    if not ctx.under_root(resolved, home):
        return None, {"isError": True, "content": [{"type": "text", "text": "BLOCKED: path outside home directory"}]}
    return resolved, None


def handle_fs_tool(name: str, args: dict[str, Any], *, ctx) -> dict[str, Any] | None:
    if name not in {"fs.read", "fs.write", "fs.list"}:
        return None

    p = os.path.expanduser(args.get("path", ""))
    path, err = _validate_home_path(p, ctx)
    if err:
        if name == "fs.write" and p and Path(p).name in _MCP_BLOCKED_FILES:
            return {"isError": True, "content": [{"type": "text", "text": f"BLOCKED: writing {Path(p).name} is not allowed"}]}
        return err

    try:
        if name == "fs.read":
            with open(path, "rb") as f:
                data = f.read(args.get("max_bytes", 200000))
            return text_content(data.decode("utf-8", "replace"))
        if name == "fs.write":
            content = args.get("content", "")
            os.makedirs(os.path.dirname(str(path)) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return text_content(f"wrote {len(content)} bytes to {path}")
        if name == "fs.list":
            return text_content(json.dumps(sorted(os.listdir(path))))
    except PermissionError:
        return {"isError": True, "content": [{"type": "text", "text": "ERROR: permission denied"}]}
    except FileNotFoundError:
        msg = "ERROR: directory not found" if name == "fs.list" else "ERROR: file not found"
        return {"isError": True, "content": [{"type": "text", "text": msg}]}
    return None
