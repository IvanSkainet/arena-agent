"""MCP filesystem search tools: fs.search and fs.grep.

fs.search — search file contents by regex pattern, with optional glob filter
            and context lines. Returns matches with file path, line number,
            and matching line content.

fs.grep   — alias for fs.search (same behavior, different name for users
            familiar with grep).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from arena.files.sandbox import SENSITIVE_FILE_BASENAMES
from arena.mcp.tool_utils import text_content

_MCP_BLOCKED_FILES = SENSITIVE_FILE_BASENAMES

# Safety limits
_MAX_FILES_SCANNED = 500
_MAX_FILE_SIZE = 512 * 1024  # 512 KB per file
_MAX_RESULTS = 200


def _validate_search_path(path: str, ctx) -> tuple[Path | None, dict[str, Any] | None]:
    """Validate that path is inside home and not a blocked file."""
    if not path:
        return None, {"isError": True, "content": [{"type": "text", "text": "ERROR: missing 'path' argument"}]}
    resolved = Path(path).resolve()
    home = Path.home().resolve()
    if not ctx.under_root(resolved, home):
        return None, {"isError": True, "content": [{"type": "text", "text": "BLOCKED: path outside home directory"}]}
    return resolved, None


def handle_fs_search_tool(name: str, args: dict[str, Any], *, ctx) -> dict[str, Any] | None:
    """Handle fs.search and fs.grep MCP tools."""
    if name not in {"fs.search", "fs.grep"}:
        return None

    path_str = os.path.expanduser(args.get("path", ""))
    pattern = args.get("pattern", args.get("query", ""))
    glob_filter = args.get("glob", args.get("file_pattern", ""))
    max_results = min(int(args.get("max_results", 50)), _MAX_RESULTS)
    context_lines = int(args.get("context", 0))
    case_insensitive = bool(args.get("ignore_case", False))

    if not pattern:
        return {"isError": True, "content": [{"type": "text", "text": "ERROR: missing 'pattern' argument"}]}

    path, err = _validate_search_path(path_str, ctx)
    if err:
        return err

    # Compile regex
    flags = re.IGNORECASE if case_insensitive else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error as e:
        return {"isError": True, "content": [{"type": "text", "text": f"ERROR: invalid regex pattern: {e}"}]}

    # Determine search root
    if path.is_file():
        search_files = [path]
    elif path.is_dir():
        search_files = _collect_files(path, glob_filter)
    else:
        return {"isError": True, "content": [{"type": "text", "text": f"ERROR: path not found: {path}"}]}

    results = []
    files_scanned = 0
    for fpath in search_files:
        if files_scanned >= _MAX_FILES_SCANNED:
            break
        if fpath.name in _MCP_BLOCKED_FILES:
            continue
        files_scanned += 1
        matches = _search_file(fpath, regex, context_lines)
        results.extend(matches)
        if len(results) >= max_results:
            results = results[:max_results]
            break

    # Format output
    if not results:
        return text_content(f"No matches found for '{pattern}' in {path}")

    lines = [f"Found {len(results)} match(es) for '{pattern}' in {path} ({files_scanned} files scanned):\n"]
    for m in results:
        if context_lines > 0 and m.get("context_before"):
            for cl in m["context_before"]:
                lines.append(f"{m['file']}:{cl['line']}:  {cl['text']}")
        lines.append(f"{m['file']}:{m['line']}:  {m['text']}")
        if context_lines > 0 and m.get("context_after"):
            for cl in m["context_after"]:
                lines.append(f"{m['file']}:{cl['line']}:  {cl['text']}")
    return text_content("\n".join(lines))


def _collect_files(root: Path, glob_filter: str) -> list[Path]:
    """Collect files under root, optionally filtered by glob pattern."""
    files = []
    if glob_filter:
        files = sorted(root.rglob(glob_filter))
        # Filter to only files, not directories
        files = [f for f in files if f.is_file()]
    else:
        for dirpath, dirnames, filenames in os.walk(root):
            # Skip hidden directories and common junk
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in {"__pycache__", "node_modules", ".git", "venv", ".venv"}]
            for fname in sorted(filenames):
                if fname in _MCP_BLOCKED_FILES:
                    continue
                files.append(Path(dirpath) / fname)
            if len(files) >= _MAX_FILES_SCANNED:
                break
    return files[:_MAX_FILES_SCANNED]


def _search_file(fpath: Path, regex: re.Pattern, context_lines: int) -> list[dict[str, Any]]:
    """Search a single file for regex matches. Returns list of match dicts."""
    results = []
    try:
        if fpath.stat().st_size > _MAX_FILE_SIZE:
            return results
        content = fpath.read_text(encoding="utf-8", errors="replace")
    except (PermissionError, OSError):
        return results

    lines = content.split("\n")
    for i, line in enumerate(lines, start=1):
        if regex.search(line):
            match = {"file": str(fpath), "line": i, "text": line.rstrip()}
            if context_lines > 0:
                match["context_before"] = [
                    {"line": j, "text": lines[j - 1].rstrip()}
                    for j in range(max(1, i - context_lines), i)
                ]
                match["context_after"] = [
                    {"line": j, "text": lines[j - 1].rstrip()}
                    for j in range(i + 1, min(len(lines) + 1, i + 1 + context_lines))
                ]
            results.append(match)
    return results
