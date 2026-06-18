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
    if name not in {"fs.read", "fs.write", "fs.list", "fs.edit"}:
        return None

    p = os.path.expanduser(args.get("path", ""))
    path, err = _validate_home_path(p, ctx)
    if err:
        if name == "fs.write" and p and Path(p).name in _MCP_BLOCKED_FILES:
            return {"isError": True, "content": [{"type": "text", "text": f"BLOCKED: writing {Path(p).name} is not allowed"}]}
        if name == "fs.edit" and p and Path(p).name in _MCP_BLOCKED_FILES:
            return {"isError": True, "content": [{"type": "text", "text": f"BLOCKED: editing {Path(p).name} is not allowed"}]}
        return err

    # fs.edit has its own find-and-replace logic with richer error messages.
    if name == "fs.edit":
        return _handle_fs_edit(path, args)

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

    # fs.edit is handled separately because it needs the file to already exist
    # (the try/except above catches FileNotFoundError for read/write/list, but
    # fs.edit has its own error messages).
    return None


def _handle_fs_edit(path: Path, args: dict[str, Any]) -> dict[str, Any]:
    """find-and-replace in a file. Mirrors Anthropic str_replace_editor semantics."""
    old_text = args.get("old_text", "")
    new_text = args.get("new_text", "")
    replace_all = bool(args.get("replace_all", False))

    if not old_text:
        return {"isError": True, "content": [{"type": "text", "text": "ERROR: missing or empty 'old_text' argument"}]}

    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"isError": True, "content": [{"type": "text", "text": "ERROR: file not found"}]}
    except PermissionError:
        return {"isError": True, "content": [{"type": "text", "text": "ERROR: permission denied"}]}
    except UnicodeDecodeError:
        return {"isError": True, "content": [{"type": "text", "text": "ERROR: file is not valid utf-8 (binary file)"}]}

    count = content.count(old_text)
    if count == 0:
        return {"isError": True, "content": [{"type": "text", "text": f"ERROR: old_text not found in {path}"}]}
    if count > 1 and not replace_all:
        return {"isError": True, "content": [{"type": "text", "text": f"ERROR: old_text matches {count} times in {path}; make it unique or set replace_all=true"}]}

    if old_text == new_text:
        return text_content(f"no changes (old_text == new_text) in {path}")

    if replace_all:
        new_content = content.replace(old_text, new_text)
    else:
        # Replace only the first (and unique) occurrence
        new_content = content.replace(old_text, new_text, 1)

    try:
        path.write_text(new_content, encoding="utf-8")
    except PermissionError:
        return {"isError": True, "content": [{"type": "text", "text": "ERROR: permission denied (cannot write)"}]}

    replacements = count if replace_all else 1
    return text_content(f"edited {path}: {replacements} replacement(s), {len(new_content)} bytes total")
