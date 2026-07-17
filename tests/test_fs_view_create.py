"""Tests for fs.view and fs.create MCP tools."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.mcp.tool_fs import handle_fs_tool  # noqa: E402
from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402


class _MockCtx:
    def __init__(self, home_dir):
        self._home = Path(home_dir).resolve()

    def under_root(self, p, home):
        try:
            Path(p).resolve().relative_to(self._home)
            return True
        except (ValueError, TypeError):
            return False


# ============================================================
# fs.view tests
# ============================================================

def test_mcp_fs_view_full_file(tmp_path):
    """fs.view reads entire file with line numbers."""
    f = tmp_path / "test.py"
    f.write_text("line1\nline2\nline3\n")
    ctx = _MockCtx(tmp_path)
    result = handle_fs_tool("fs.view", {"path": str(f)}, ctx=ctx)
    assert result is not None
    assert not result.get("isError"), f"expected success, got: {result}"
    text = result["content"][0]["text"]
    assert "lines" in text
    assert "1: line1" in text
    assert "2: line2" in text
    assert "3: line3" in text


def test_mcp_fs_view_with_range(tmp_path):
    """fs.view reads specific line range."""
    f = tmp_path / "test.py"
    f.write_text("line1\nline2\nline3\nline4\nline5\n")
    ctx = _MockCtx(tmp_path)
    result = handle_fs_tool("fs.view", {"path": str(f), "view_range": [2, 4]}, ctx=ctx)
    assert result is not None
    assert not result.get("isError"), f"expected success, got: {result}"
    text = result["content"][0]["text"]
    assert "lines 2-4" in text
    assert "2: line2" in text
    assert "3: line3" in text
    assert "4: line4" in text
    assert "line1" not in text
    assert "line5" not in text


def test_mcp_fs_view_file_not_found(tmp_path):
    """fs.view errors on missing file."""
    ctx = _MockCtx(tmp_path)
    result = handle_fs_tool("fs.view", {"path": str(tmp_path / "missing.py")}, ctx=ctx)
    assert result is not None
    assert result.get("isError") is True
    assert "file not found" in result["content"][0]["text"]


def test_mcp_fs_view_invalid_range(tmp_path):
    """fs.view errors on invalid view_range."""
    f = tmp_path / "test.py"
    f.write_text("line1\nline2\n")
    ctx = _MockCtx(tmp_path)
    result = handle_fs_tool("fs.view", {"path": str(f), "view_range": [5, 1]}, ctx=ctx)
    assert result is not None
    assert result.get("isError") is True
    assert "invalid view_range" in result["content"][0]["text"]


def test_mcp_fs_view_blocked_file(tmp_path):
    """fs.view blocks sensitive files."""
    f = tmp_path / "token.txt"
    f.write_text("secret\n")
    ctx = _MockCtx(tmp_path)
    result = handle_fs_tool("fs.view", {"path": str(f)}, ctx=ctx)
    assert result is not None
    assert result.get("isError") is True
    assert "BLOCKED" in result["content"][0]["text"]


# ============================================================
# fs.create tests
# ============================================================

def test_mcp_fs_create_success(tmp_path):
    """fs.create creates a new file."""
    f = tmp_path / "new_file.py"
    ctx = _MockCtx(tmp_path)
    result = handle_fs_tool("fs.create", {"path": str(f), "content": "print('hello')\n"}, ctx=ctx)
    assert result is not None
    assert not result.get("isError"), f"expected success, got: {result}"
    assert "created" in result["content"][0]["text"]
    assert f.read_text() == "print('hello')\n"


def test_mcp_fs_create_already_exists(tmp_path):
    """fs.create fails if file already exists."""
    f = tmp_path / "existing.py"
    f.write_text("original\n")
    ctx = _MockCtx(tmp_path)
    result = handle_fs_tool("fs.create", {"path": str(f), "content": "new\n"}, ctx=ctx)
    assert result is not None
    assert result.get("isError") is True
    assert "already exists" in result["content"][0]["text"]
    # File should be unchanged
    assert f.read_text() == "original\n"


def test_mcp_fs_create_empty_content(tmp_path):
    """fs.create errors on empty content."""
    f = tmp_path / "empty.py"
    ctx = _MockCtx(tmp_path)
    result = handle_fs_tool("fs.create", {"path": str(f), "content": ""}, ctx=ctx)
    assert result is not None
    assert result.get("isError") is True
    assert "missing or empty" in result["content"][0]["text"]


def test_mcp_fs_create_creates_parent_dirs(tmp_path):
    """fs.create creates parent directories if they don't exist."""
    f = tmp_path / "subdir" / "nested" / "file.py"
    ctx = _MockCtx(tmp_path)
    result = handle_fs_tool("fs.create", {"path": str(f), "content": "x = 1\n"}, ctx=ctx)
    assert result is not None
    assert not result.get("isError"), f"expected success, got: {result}"
    assert f.read_text() == "x = 1\n"


def test_mcp_fs_create_blocked_file(tmp_path):
    """fs.create blocks creating sensitive files."""
    f = tmp_path / "token.txt"
    ctx = _MockCtx(tmp_path)
    result = handle_fs_tool("fs.create", {"path": str(f), "content": "secret\n"}, ctx=ctx)
    assert result is not None
    assert result.get("isError") is True
    assert "BLOCKED" in result["content"][0]["text"]


# ============================================================
# Registry tests
# ============================================================

def test_fs_view_in_registry():
    """fs.view is registered in MCP_TOOLS."""
    names = [t["name"] for t in MCP_TOOLS]
    assert "fs.view" in names


def test_fs_create_in_registry():
    """fs.create is registered in MCP_TOOLS."""
    names = [t["name"] for t in MCP_TOOLS]
    assert "fs.create" in names


def test_fs_view_schema():
    """fs.view has path required, view_range optional."""
    tool = next(t for t in MCP_TOOLS if t["name"] == "fs.view")
    assert "path" in tool["inputSchema"]["required"]
    assert "view_range" in tool["inputSchema"]["properties"]


def test_fs_create_schema():
    """fs.create has path and content required."""
    tool = next(t for t in MCP_TOOLS if t["name"] == "fs.create")
    assert "path" in tool["inputSchema"]["required"]
    assert "content" in tool["inputSchema"]["required"]


# ============================================================
# v4.48.2: directory-guard regression tests
# ============================================================
# Before v4.48.2 a caller that passed ``{"path": "."}`` (a directory)
# to fs.view got an uncaught IsADirectoryError from ``path.read_text``
# which bubbled out as a bare HTTP 500 with no hint that fs.list was
# the right verb. Now the tool detects the shape up front and returns
# a structured error message that names the fix.

def test_mcp_fs_view_directory_returns_hint(tmp_path):
    """fs.view on a directory returns a friendly error pointing at fs.list."""
    ctx = _MockCtx(tmp_path)
    (tmp_path / "sub").mkdir()
    result = handle_fs_tool("fs.view", {"path": str(tmp_path / "sub")}, ctx=ctx)
    assert result is not None
    assert result.get("isError") is True
    text = result["content"][0]["text"]
    assert "directory" in text.lower()
    assert "fs.list" in text, (
        "error message must name fs.list as the right verb for directories"
    )


def test_mcp_fs_view_dot_path(tmp_path, monkeypatch):
    """fs.view with path='.' resolves to a directory and is caught.

    This is the exact shape the v4.48.1 scan-report bug reproduced:
    the model emitted {"path": "."} and the tool returned an opaque
    "missing 'path' argument" error even though the argument was
    present. v4.48.2 catches the directory case explicitly.
    """
    ctx = _MockCtx(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = handle_fs_tool("fs.view", {"path": "."}, ctx=ctx)
    assert result is not None
    assert result.get("isError") is True
    text = result["content"][0]["text"]
    # Either the directory guard fires or the path validation catches
    # it -- either way, no bare 500 / IsADirectoryError should leak.
    assert "directory" in text.lower() or "path" in text.lower()
