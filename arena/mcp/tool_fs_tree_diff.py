"""MCP filesystem tree and diff tools: fs.tree and fs.diff.

fs.tree — show directory tree structure with optional depth limit and
          glob filter. Returns a text tree like the `tree` command.

fs.diff — compare two text files and return unified diff. Uses Python's
          difflib.unified_diff for output.
"""
from __future__ import annotations

import os
import difflib
from pathlib import Path
from typing import Any

from arena.files.sandbox import SENSITIVE_FILE_BASENAMES
from arena.mcp.tool_utils import text_content

_MCP_BLOCKED_FILES = SENSITIVE_FILE_BASENAMES

# Safety limits
_MAX_TREE_ENTRIES = 1000
_MAX_DIFF_SIZE = 512 * 1024  # 512 KB per file for diff


def _validate_path(path_str: str, ctx) -> tuple[Path | None, dict[str, Any] | None]:
    """Validate that path is inside home and not a blocked file."""
    if not path_str:
        return None, {"isError": True, "content": [{"type": "text", "text": "ERROR: missing 'path' argument"}]}
    if Path(path_str).name in _MCP_BLOCKED_FILES:
        return None, {"isError": True, "content": [{"type": "text", "text": f"BLOCKED: accessing {Path(path_str).name} is not allowed"}]}
    resolved = Path(path_str).resolve()
    home = Path.home().resolve()
    if not ctx.under_root(resolved, home):
        return None, {"isError": True, "content": [{"type": "text", "text": "BLOCKED: path outside home directory"}]}
    return resolved, None


def handle_fs_tree_diff_tool(name: str, args: dict[str, Any], *, ctx) -> dict[str, Any] | None:
    """Handle fs.tree and fs.diff MCP tools."""
    if name not in {"fs.tree", "fs.diff"}:
        return None

    if name == "fs.tree":
        return _handle_fs_tree(args, ctx)
    if name == "fs.diff":
        return _handle_fs_diff(args, ctx)
    return None


def _handle_fs_tree(args: dict[str, Any], ctx) -> dict[str, Any]:
    """Show directory tree structure."""
    path_str = os.path.expanduser(args.get("path", ""))
    max_depth = int(args.get("max_depth", 3))
    max_depth = min(max(max_depth, 1), 10)  # clamp 1-10
    show_files = bool(args.get("show_files", True))
    glob_filter = args.get("glob", "")

    path, err = _validate_path(path_str, ctx)
    if err:
        return err

    if not path.exists():
        return {"isError": True, "content": [{"type": "text", "text": f"ERROR: path not found: {path}"}]}
    if path.is_file():
        return text_content(f"{path.name}  (file, {path.stat().st_size} bytes)")

    entries = []
    _build_tree(path, "", 0, max_depth, show_files, glob_filter, entries)
    if not entries:
        return text_content(f"{path}\n(empty directory)")
    return text_content("\n".join(entries))


def _build_tree(dir_path: Path, prefix: str, depth: int, max_depth: int, show_files: bool, glob_filter: str, entries: list[str]) -> None:
    """Recursively build tree lines."""
    if depth >= max_depth or len(entries) >= _MAX_TREE_ENTRIES:
        return
    try:
        items = sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except (PermissionError, OSError):
        return

    # Filter
    filtered = []
    for item in items:
        if item.name.startswith("."):
            continue
        if item.name in {"__pycache__", "node_modules", ".git", "venv", ".venv"}:
            continue
        if item.is_dir():
            filtered.append(item)
        elif show_files:
            if glob_filter:
                if item.match(glob_filter):
                    filtered.append(item)
            else:
                filtered.append(item)

    for i, item in enumerate(filtered):
        is_last = (i == len(filtered) - 1)
        connector = "└── " if is_last else "├── "
        if len(entries) >= _MAX_TREE_ENTRIES:
            entries.append(prefix + "└── ... (truncated)")
            return
        if item.is_dir():
            entries.append(prefix + connector + item.name + "/")
            extension = "    " if is_last else "│   "
            _build_tree(item, prefix + extension, depth + 1, max_depth, show_files, glob_filter, entries)
        else:
            size = item.stat().st_size
            size_str = f"  ({_format_size(size)})" if size > 0 else ""
            entries.append(prefix + connector + item.name + size_str)


def _format_size(size: int) -> str:
    """Format file size in human-readable form."""
    if size < 1024:
        return f"{size}B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f}KB"
    else:
        return f"{size / (1024 * 1024):.1f}MB"


def _handle_fs_diff(args: dict[str, Any], ctx) -> dict[str, Any]:
    """Compare two files and return unified diff."""
    path_a_str = os.path.expanduser(args.get("path_a", args.get("old_path", "")))
    path_b_str = os.path.expanduser(args.get("path_b", args.get("new_path", "")))

    if not path_a_str or not path_b_str:
        return {"isError": True, "content": [{"type": "text", "text": "ERROR: both 'path_a' and 'path_b' are required"}]}

    path_a, err_a = _validate_path(path_a_str, ctx)
    if err_a:
        return err_a
    path_b, err_b = _validate_path(path_b_str, ctx)
    if err_b:
        return err_b

    # Read both files
    try:
        if path_a.stat().st_size > _MAX_DIFF_SIZE or path_b.stat().st_size > _MAX_DIFF_SIZE:
            return {"isError": True, "content": [{"type": "text", "text": f"ERROR: file too large (max {_MAX_DIFF_SIZE // 1024}KB per file)"}]}
    except OSError as e:
        return {"isError": True, "content": [{"type": "text", "text": f"ERROR: {e}"}]}

    try:
        lines_a = path_a.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    except FileNotFoundError:
        return {"isError": True, "content": [{"type": "text", "text": f"ERROR: file not found: {path_a}"}]}
    except PermissionError:
        return {"isError": True, "content": [{"type": "text", "text": f"ERROR: permission denied: {path_a}"}]}

    try:
        lines_b = path_b.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    except FileNotFoundError:
        return {"isError": True, "content": [{"type": "text", "text": f"ERROR: file not found: {path_b}"}]}
    except PermissionError:
        return {"isError": True, "content": [{"type": "text", "text": f"ERROR: permission denied: {path_b}"}]}

    diff = list(difflib.unified_diff(lines_a, lines_b, fromfile=str(path_a), tofile=str(path_b), lineterm=""))

    if not diff:
        return text_content(f"Files are identical:\n  {path_a}\n  {path_b}")

    return text_content("".join(diff))
