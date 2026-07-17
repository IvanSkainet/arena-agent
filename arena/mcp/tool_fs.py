"""MCP filesystem tools."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from arena.files.safe_edit import apply_preview, create_preview, rollback_change
from arena.files.sandbox import SENSITIVE_FILE_BASENAMES
from arena.mcp.tool_utils import text_content

_MCP_BLOCKED_FILES = SENSITIVE_FILE_BASENAMES


def _validate_home_path(path: str, ctx) -> tuple[Path | None, dict[str, Any] | None]:
    if not path:
        return None, {"isError": True, "content": [{"type": "text", "text": "ERROR: missing 'path' argument"}]}
    if Path(path).name in _MCP_BLOCKED_FILES:
        return None, {"isError": True, "content": [{"type": "text", "text": f"BLOCKED: accessing {Path(path).name} is not allowed"}]}
    resolved = Path(path).resolve()
    home = Path.home().resolve()
    if not ctx.under_root(resolved, home):
        return None, {"isError": True, "content": [{"type": "text", "text": "BLOCKED: path outside home directory"}]}
    return resolved, None



def _safe_edit_text_result(result: dict[str, Any]) -> dict[str, Any]:
    if not result.get("ok"):
        return {"isError": True, "content": [{"type": "text", "text": f"ERROR: {result.get('error', 'unknown error')}"}]}
    if result.get("preview"):
        if result.get("replacements") == 0 and result.get("message"):
            return text_content(result["message"])
        text = (
            f"preview_id={result['preview_id']} path={result['path']} replacements={result['replacements']} "
            f"bytes_before={result['bytes_before']} bytes_after={result['bytes_after']}\n\n{result.get('diff', '')}"
        )
        return text_content(text)
    if result.get("rolled_back"):
        return text_content(f"rolled back {result['path']} via {result['rollback_id']} ({result['bytes']} bytes)")
    if result.get("applied"):
        return text_content(
            f"edited {result['path']}: {result['replacements']} replacement(s), {result['bytes']} bytes total, rollback_id={result['rollback_id']}"
        )
    return text_content(json.dumps(result, ensure_ascii=False))



def handle_fs_tool(name: str, args: dict[str, Any], *, ctx) -> dict[str, Any] | None:
    if name not in {"fs.read", "fs.write", "fs.list", "fs.edit", "fs.view", "fs.create", "fs.edit_apply", "fs.edit_rollback"}:
        return None

    if name == "fs.edit_apply":
        preview_id = str(args.get("preview_id", "")).strip()
        if not preview_id:
            return {"isError": True, "content": [{"type": "text", "text": "ERROR: missing 'preview_id' argument"}]}
        return _safe_edit_text_result(apply_preview(preview_id))

    if name == "fs.edit_rollback":
        rollback_id = str(args.get("rollback_id", "")).strip()
        if not rollback_id:
            return {"isError": True, "content": [{"type": "text", "text": "ERROR: missing 'rollback_id' argument"}]}
        return _safe_edit_text_result(rollback_change(rollback_id, force=bool(args.get("force", False))))

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

    if name == "fs.edit":
        old_text = args.get("old_text", "")
        new_text = args.get("new_text", "")
        preview = create_preview(path, old_text, new_text, replace_all=bool(args.get("replace_all", False)))
        if bool(args.get("preview", False)):
            return _safe_edit_text_result(preview)
        if not preview.get("ok") or preview.get("replacements") == 0:
            return _safe_edit_text_result(preview)
        return _safe_edit_text_result(apply_preview(preview["preview_id"]))
    if name == "fs.view":
        return _handle_fs_view(path, args)
    if name == "fs.create":
        return _handle_fs_create(path, args)
    return None



def _handle_fs_view(path: Path, args: dict[str, Any]) -> dict[str, Any]:
    view_range = args.get("view_range")
    # v4.48.2: guard directory targets up front. Previously a call
    # like ``fs.view {"path": "."}`` reached ``read_text`` with a
    # directory path, which raised ``IsADirectoryError`` -- not one
    # of the catches below -- and bubbled out as an uncaught 500
    # from the MCP dispatcher. The model then saw a bare HTTP 500
    # with no hint that ``fs.list`` was the right verb. The message
    # names both the mistake and the fix so a follow-up call can
    # succeed without another round trip.
    if path.is_dir():
        return {"isError": True, "content": [{"type": "text",
            "text": f"ERROR: {path} is a directory; use fs.list for directories, fs.view is for files"}]}
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"isError": True, "content": [{"type": "text", "text": "ERROR: file not found"}]}
    except IsADirectoryError:
        # Defence-in-depth in case is_dir() was racy (rare on
        # network filesystems where the entry flips between file
        # and directory).
        return {"isError": True, "content": [{"type": "text",
            "text": f"ERROR: {path} is a directory; use fs.list for directories"}]}
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
        end = min(end, total_lines)
        numbered = [f"{str(i).rjust(len(str(end)))}: {line}" for i, line in enumerate(lines[start - 1:end], start=start)]
        return text_content(f"{path} (lines {start}-{end} of {total_lines}):\n" + "\n".join(numbered))
    numbered = [f"{str(i).rjust(len(str(total_lines)))}: {line}" for i, line in enumerate(lines, start=1)]
    return text_content(f"{path} ({total_lines} lines):\n" + "\n".join(numbered))



def _handle_fs_create(path: Path, args: dict[str, Any]) -> dict[str, Any]:
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
