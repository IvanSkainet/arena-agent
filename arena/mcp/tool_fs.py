"""MCP filesystem tools."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from arena.files.sandbox import SENSITIVE_FILE_BASENAMES
from arena.mcp.tool_utils import text_content

# Reuse the canonical sensitive-file set from the sandbox layer so fs.*
# operations can never drift out of sync with the REST endpoints.
_MCP_BLOCKED_FILES = SENSITIVE_FILE_BASENAMES


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
    if name not in {"fs.read", "fs.write", "fs.list", "fs.edit", "fs.view", "fs.create"}:
        return None

    p = os.path.expanduser(args.get("path", ""))
    path, err = _validate_home_path(p, ctx)
    if err:
        if name == "fs.write" and p and Path(p).name in _MCP_BLOCKED_FILES:
            return {"isError": True, "content": [{"type": "text", "text": f"BLOCKED: writing {Path(p).name} is not allowed"}]}
        if name == "fs.edit" and p and Path(p).name in _MCP_BLOCKED_FILES:
            return {"isError": True, "content": [{"type": "text", "text": f"BLOCKED: editing {Path(p).name} is not allowed"}]}
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

    # fs.edit is handled separately because it needs the file to already exist
    # (the try/except above catches FileNotFoundError for read/write/list, but
    # fs.edit has its own error messages).
    if name == "fs.edit":
        return _handle_fs_edit(path, args)

    # fs.view: read file with optional line range (mirrors str_replace_editor "view")
    if name == "fs.view":
        return _handle_fs_view(path, args)

    # fs.create: create a new file (fails if it already exists)
    if name == "fs.create":
        return _handle_fs_create(path, args)

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



def _handle_fs_view(path: Path, args: dict[str, Any]) -> dict[str, Any]:
    """Read a file with optional line range. Mirrors str_replace_editor 'view' command."""
    view_range = args.get("view_range")

    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"isError": True, "content": [{"type": "text", "text": "ERROR: file not found"}]}
    except PermissionError:
        return {"isError": True, "content": [{"type": "text", "text": "ERROR: permission denied"}]}
    except UnicodeDecodeError:
        return {"isError": True, "content": [{"type": "text", "text": "ERROR: file is not valid utf-8 (binary file)"}]}

    lines = content.split("\n")
    total_lines = len(lines)

    if view_range:
        if not isinstance(view_range, list) or len(view_range) != 2:
            return {"isError": True, "content": [{"type": "text", "text": "ERROR: view_range must be a list of [start, end] line numbers (1-indexed)"}]}
        try:
            start, end = int(view_range[0]), int(view_range[1])
        except (ValueError, TypeError):
            return {"isError": True, "content": [{"type": "text", "text": "ERROR: view_range values must be integers"}]}
        if start < 1 or end < 1 or start > end:
            return {"isError": True, "content": [{"type": "text", "text": f"ERROR: invalid view_range [{start}, {end}] — must be 1-indexed with start <= end"}]}
        if start > total_lines:
            return {"isError": True, "content": [{"type": "text", "text": f"ERROR: start line {start} exceeds file length ({total_lines} lines)"}]}
        # Clamp end to total_lines
        end = min(end, total_lines)
        selected = lines[start - 1:end]
        # Add line numbers (1-indexed, matching str_replace_editor format)
        numbered = []
        for i, line in enumerate(selected, start=start):
            width = len(str(end))
            numbered.append(f"{str(i).rjust(width)}: {line}")
        result_text = "\n".join(numbered)
        return text_content(f"{path} (lines {start}-{end} of {total_lines}):\n{result_text}")
    else:
        # Full file with line numbers
        numbered = []
        width = len(str(total_lines))
        for i, line in enumerate(lines, start=1):
            numbered.append(f"{str(i).rjust(width)}: {line}")
        result_text = "\n".join(numbered)
        return text_content(f"{path} ({total_lines} lines):\n{result_text}")


def _handle_fs_create(path: Path, args: dict[str, Any]) -> dict[str, Any]:
    """Create a new file. Fails if the file already exists. Mirrors str_replace_editor 'create'."""
    content = args.get("content", "")
    if not content:
        return {"isError": True, "content": [{"type": "text", "text": "ERROR: missing or empty 'content' argument"}]}

    if path.exists():
        return {"isError": True, "content": [{"type": "text", "text": f"ERROR: file already exists: {path} (use fs.edit to modify existing files)"}]}

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except PermissionError:
        return {"isError": True, "content": [{"type": "text", "text": "ERROR: permission denied"}]}
    except Exception as e:
        return {"isError": True, "content": [{"type": "text", "text": f"ERROR: {type(e).__name__}: {e}"}]}

    return text_content(f"created {path}: {len(content)} bytes")