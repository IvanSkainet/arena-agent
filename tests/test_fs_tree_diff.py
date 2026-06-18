"""Tests for fs.tree and fs.diff MCP tools."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.mcp.tool_fs_tree_diff import handle_fs_tree_diff_tool  # noqa: E402
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


def _make_files(tmp_path, files: dict[str, str]):
    for rel, content in files.items():
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)


# ============================================================
# fs.tree tests
# ============================================================

def test_fs_tree_basic(tmp_path):
    """fs.tree shows directory structure."""
    _make_files(tmp_path, {
        "file1.py": "x = 1\n",
        "file2.py": "y = 2\n",
        "subdir/file3.py": "z = 3\n",
    })
    ctx = _MockCtx(tmp_path)
    result = handle_fs_tree_diff_tool("fs.tree", {"path": str(tmp_path)}, ctx=ctx)
    assert result is not None
    text = result["content"][0]["text"]
    assert "file1.py" in text
    assert "file2.py" in text
    assert "subdir/" in text
    assert "file3.py" in text


def test_tree_single_file(tmp_path):
    """fs.tree on a single file returns file info."""
    f = tmp_path / "test.py"
    f.write_text("hello\n")
    ctx = _MockCtx(tmp_path)
    result = handle_fs_tree_diff_tool("fs.tree", {"path": str(f)}, ctx=ctx)
    assert result is not None
    text = result["content"][0]["text"]
    assert "test.py" in text
    assert "file" in text
    assert "6 bytes" in text  # "hello\n" = 6 bytes


def test_fs_tree_max_depth(tmp_path):
    """fs.tree respects max_depth."""
    _make_files(tmp_path, {
        "a/b/c/deep.py": "x\n",
    })
    ctx = _MockCtx(tmp_path)
    result = handle_fs_tree_diff_tool("fs.tree", {"path": str(tmp_path), "max_depth": 1}, ctx=ctx)
    assert result is not None
    text = result["content"][0]["text"]
    assert "a/" in text
    assert "deep.py" not in text  # depth 3, not shown at max_depth=1


def test_fs_tree_glob_filter(tmp_path):
    """fs.tree respects glob filter for files."""
    _make_files(tmp_path, {
        "match.py": "x\n",
        "match.txt": "y\n",
        "other.py": "z\n",
    })
    ctx = _MockCtx(tmp_path)
    result = handle_fs_tree_diff_tool("fs.tree", {"path": str(tmp_path), "glob": "*.py"}, ctx=ctx)
    assert result is not None
    text = result["content"][0]["text"]
    assert "match.py" in text
    assert "other.py" in text
    assert "match.txt" not in text


def test_fs_tree_show_files_false(tmp_path):
    """fs.tree with show_files=false shows only directories."""
    _make_files(tmp_path, {
        "file.py": "x\n",
        "subdir/file2.py": "y\n",
    })
    ctx = _MockCtx(tmp_path)
    result = handle_fs_tree_diff_tool("fs.tree", {"path": str(tmp_path), "show_files": False}, ctx=ctx)
    assert result is not None
    text = result["content"][0]["text"]
    assert "subdir/" in text
    assert "file.py" not in text
    assert "file2.py" not in text


def test_fs_tree_empty_dir(tmp_path):
    """fs.tree on empty directory returns empty message."""
    ctx = _MockCtx(tmp_path)
    result = handle_fs_tree_diff_tool("fs.tree", {"path": str(tmp_path)}, ctx=ctx)
    assert result is not None
    text = result["content"][0]["text"]
    assert "empty" in text.lower()


def test_fs_tree_path_not_found(tmp_path):
    """fs.tree errors on non-existent path."""
    ctx = _MockCtx(tmp_path)
    result = handle_fs_tree_diff_tool("fs.tree", {"path": str(tmp_path / "nonexistent")}, ctx=ctx)
    assert result is not None
    assert result.get("isError") is True
    assert "not found" in result["content"][0]["text"].lower()


def test_fs_tree_skips_hidden(tmp_path):
    """fs.tree skips hidden files and directories."""
    _make_files(tmp_path, {
        ".hidden": "x\n",
        ".git/config": "y\n",
        "visible.py": "z\n",
    })
    ctx = _MockCtx(tmp_path)
    result = handle_fs_tree_diff_tool("fs.tree", {"path": str(tmp_path)}, ctx=ctx)
    assert result is not None
    text = result["content"][0]["text"]
    assert "visible.py" in text
    assert ".hidden" not in text
    assert ".git" not in text


# ============================================================
# fs.diff tests
# ============================================================

def test_fs_diff_different_files(tmp_path):
    """fs.diff shows differences between two files."""
    f1 = tmp_path / "old.py"
    f1.write_text("line1\nline2\nline3\n")
    f2 = tmp_path / "new.py"
    f2.write_text("line1\nline2_changed\nline3\nline4\n")
    ctx = _MockCtx(tmp_path)
    result = handle_fs_tree_diff_tool("fs.diff", {"path_a": str(f1), "path_b": str(f2)}, ctx=ctx)
    assert result is not None
    assert not result.get("isError")
    text = result["content"][0]["text"]
    assert "---" in text  # unified diff marker
    assert "+++" in text
    assert "line2_changed" in text
    assert "line4" in text


def test_fs_diff_identical_files(tmp_path):
    """fs.diff on identical files returns identical message."""
    f1 = tmp_path / "a.py"
    f1.write_text("same content\n")
    f2 = tmp_path / "b.py"
    f2.write_text("same content\n")
    ctx = _MockCtx(tmp_path)
    result = handle_fs_tree_diff_tool("fs.diff", {"path_a": str(f1), "path_b": str(f2)}, ctx=ctx)
    assert result is not None
    text = result["content"][0]["text"]
    assert "identical" in text.lower()


def test_fs_diff_missing_path_arg(tmp_path):
    """fs.diff errors when path_a or path_b is missing."""
    ctx = _MockCtx(tmp_path)
    result = handle_fs_tree_diff_tool("fs.diff", {"path_a": str(tmp_path / "a.py")}, ctx=ctx)
    assert result is not None
    assert result.get("isError") is True
    assert "required" in result["content"][0]["text"].lower()


def test_fs_diff_file_not_found(tmp_path):
    """fs.diff errors when file doesn't exist."""
    f1 = tmp_path / "exists.py"
    f1.write_text("x\n")
    ctx = _MockCtx(tmp_path)
    result = handle_fs_tree_diff_tool("fs.diff", {"path_a": str(f1), "path_b": str(tmp_path / "missing.py")}, ctx=ctx)
    assert result is not None
    assert result.get("isError") is True
    text = result["content"][0]["text"].lower()
    assert "not found" in text or "no such file" in text


def test_fs_diff_blocked_sensitive_file(tmp_path):
    """fs.diff blocks sensitive files."""
    f1 = tmp_path / "token.txt"
    f1.write_text("secret\n")
    f2 = tmp_path / "other.py"
    f2.write_text("x\n")
    ctx = _MockCtx(tmp_path)
    result = handle_fs_tree_diff_tool("fs.diff", {"path_a": str(f1), "path_b": str(f2)}, ctx=ctx)
    assert result is not None
    assert result.get("isError") is True
    assert "BLOCKED" in result["content"][0]["text"]


# ============================================================
# Registry tests
# ============================================================

def test_fs_tree_in_registry():
    names = [t["name"] for t in MCP_TOOLS]
    assert "fs.tree" in names


def test_fs_diff_in_registry():
    names = [t["name"] for t in MCP_TOOLS]
    assert "fs.diff" in names


def test_fs_tree_schema():
    tool = next(t for t in MCP_TOOLS if t["name"] == "fs.tree")
    assert "path" in tool["inputSchema"]["required"]
    assert "max_depth" in tool["inputSchema"]["properties"]
    assert "glob" in tool["inputSchema"]["properties"]


def test_fs_diff_schema():
    tool = next(t for t in MCP_TOOLS if t["name"] == "fs.diff")
    assert "path_a" in tool["inputSchema"]["required"]
    assert "path_b" in tool["inputSchema"]["required"]
