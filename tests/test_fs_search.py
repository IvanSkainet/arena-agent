"""Tests for fs.search and fs.grep MCP tools."""
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.mcp.tool_fs_search import handle_fs_search_tool  # noqa: E402
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
    """Create test files under tmp_path. files = {relative_path: content}."""
    for rel, content in files.items():
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)


# ============================================================
# fs.search basic tests
# ============================================================

def test_fs_search_finds_matches_in_file(tmp_path):
    """fs.search finds regex matches in a single file."""
    f = tmp_path / "test.py"
    f.write_text("def hello():\n    print('hello world')\n    return 42\n")
    ctx = _MockCtx(tmp_path)
    result = handle_fs_search_tool("fs.search", {"path": str(f), "pattern": "hello"}, ctx=ctx)
    assert result is not None
    assert not result.get("isError"), f"expected success, got: {result}"
    text = result["content"][0]["text"]
    assert "2 match(es)" in text or "match(es)" in text
    assert "hello world" in text


def test_fs_search_finds_matches_in_directory(tmp_path):
    """fs.search finds matches across multiple files in a directory."""
    _make_files(tmp_path, {
        "a.py": "x = 1\nTODO: fix this\n",
        "b.py": "y = 2\n# TODO: also this\n",
        "c.txt": "nothing here\n",
    })
    ctx = _MockCtx(tmp_path)
    result = handle_fs_search_tool("fs.search", {"path": str(tmp_path), "pattern": "TODO"}, ctx=ctx)
    assert result is not None
    assert not result.get("isError")
    text = result["content"][0]["text"]
    assert "2 match(es)" in text
    assert "a.py" in text
    assert "b.py" in text
    assert "c.txt" not in text


def test_fs_search_no_matches(tmp_path):
    """fs.search returns no matches message when pattern not found."""
    f = tmp_path / "test.py"
    f.write_text("hello world\n")
    ctx = _MockCtx(tmp_path)
    result = handle_fs_search_tool("fs.search", {"path": str(f), "pattern": "zzznonexistent"}, ctx=ctx)
    assert result is not None
    text = result["content"][0]["text"]
    assert "No matches" in text


def test_fs_search_missing_pattern(tmp_path):
    """fs.search errors when pattern is missing."""
    ctx = _MockCtx(tmp_path)
    result = handle_fs_search_tool("fs.search", {"path": str(tmp_path)}, ctx=ctx)
    assert result is not None
    assert result.get("isError") is True
    assert "missing" in result["content"][0]["text"].lower()


def test_fs_search_invalid_regex(tmp_path):
    """fs.search errors on invalid regex pattern."""
    ctx = _MockCtx(tmp_path)
    result = handle_fs_search_tool("fs.search", {"path": str(tmp_path), "pattern": "[invalid"}, ctx=ctx)
    assert result is not None
    assert result.get("isError") is True
    assert "invalid regex" in result["content"][0]["text"].lower()


def test_fs_search_glob_filter(tmp_path):
    """fs.search respects glob filter."""
    _make_files(tmp_path, {
        "match.py": "target_line\n",
        "match.txt": "target_line\n",
        "nomatch.py": "other_line\n",
    })
    ctx = _MockCtx(tmp_path)
    result = handle_fs_search_tool("fs.search", {"path": str(tmp_path), "pattern": "target", "glob": "*.py"}, ctx=ctx)
    assert result is not None
    text = result["content"][0]["text"]
    assert "match.py" in text
    assert "match.txt" not in text


def test_fs_search_ignore_case(tmp_path):
    """fs.search with ignore_case finds matches regardless of case."""
    f = tmp_path / "test.py"
    f.write_text("Hello World\nHELLO\nhello\n")
    ctx = _MockCtx(tmp_path)
    result = handle_fs_search_tool("fs.search", {"path": str(f), "pattern": "hello", "ignore_case": True}, ctx=ctx)
    assert result is not None
    text = result["content"][0]["text"]
    assert "3 match(es)" in text


def test_fs_search_context_lines(tmp_path):
    """fs.search with context returns surrounding lines."""
    f = tmp_path / "test.py"
    f.write_text("line1\nline2\nMATCH\nline4\nline5\n")
    ctx = _MockCtx(tmp_path)
    result = handle_fs_search_tool("fs.search", {"path": str(f), "pattern": "MATCH", "context": 1}, ctx=ctx)
    assert result is not None
    text = result["content"][0]["text"]
    # Should contain line2 (before) and line4 (after)
    assert "line2" in text
    assert "line4" in text


def test_fs_search_max_results(tmp_path):
    """fs.search respects max_results."""
    f = tmp_path / "test.py"
    f.write_text("match\n" * 100)
    ctx = _MockCtx(tmp_path)
    result = handle_fs_search_tool("fs.search", {"path": str(f), "pattern": "match", "max_results": 5}, ctx=ctx)
    assert result is not None
    text = result["content"][0]["text"]
    assert "5 match(es)" in text


def test_fs_search_path_not_found(tmp_path):
    """fs.search errors when path doesn't exist."""
    ctx = _MockCtx(tmp_path)
    result = handle_fs_search_tool("fs.search", {"path": str(tmp_path / "nonexistent"), "pattern": "x"}, ctx=ctx)
    assert result is not None
    assert result.get("isError") is True
    assert "not found" in result["content"][0]["text"].lower()


def test_fs_search_blocked_sensitive_file(tmp_path):
    """fs.search skips sensitive files."""
    f = tmp_path / "token.txt"
    f.write_text("secret_token_here\n")
    ctx = _MockCtx(tmp_path)
    result = handle_fs_search_tool("fs.search", {"path": str(tmp_path), "pattern": "secret"}, ctx=ctx)
    assert result is not None
    text = result["content"][0]["text"]
    # Should not find the match in token.txt
    assert "No matches" in text or "token.txt" not in text


def test_fs_search_skips_hidden_dirs(tmp_path):
    """fs.search skips hidden directories like .git."""
    _make_files(tmp_path, {
        ".git/config": "target_line\n",
        "real.py": "target_line\n",
    })
    ctx = _MockCtx(tmp_path)
    result = handle_fs_search_tool("fs.search", {"path": str(tmp_path), "pattern": "target"}, ctx=ctx)
    assert result is not None
    text = result["content"][0]["text"]
    assert "real.py" in text
    assert ".git" not in text


# ============================================================
# fs.grep alias tests
# ============================================================

def test_fs_grep_works_as_alias(tmp_path):
    """fs.grep works the same as fs.search."""
    f = tmp_path / "test.py"
    f.write_text("hello world\n")
    ctx = _MockCtx(tmp_path)
    result = handle_fs_search_tool("fs.grep", {"path": str(f), "pattern": "hello"}, ctx=ctx)
    assert result is not None
    assert not result.get("isError")
    assert "1 match(es)" in result["content"][0]["text"]


def test_fs_grep_returns_none_for_other_tools():
    """handle_fs_search_tool returns None for non-search/grep tools."""
    from arena.mcp.tool_fs_search import handle_fs_search_tool
    # Should return None for tools it doesn't handle
    assert handle_fs_search_tool("fs.read", {}, ctx=None) is None
    assert handle_fs_search_tool("fs.write", {}, ctx=None) is None


# ============================================================
# Registry tests
# ============================================================

def test_fs_search_in_registry():
    """fs.search is registered in MCP_TOOLS."""
    names = [t["name"] for t in MCP_TOOLS]
    assert "fs.search" in names


def test_fs_grep_in_registry():
    """fs.grep is registered in MCP_TOOLS."""
    names = [t["name"] for t in MCP_TOOLS]
    assert "fs.grep" in names


def test_fs_search_schema():
    """fs.search has path and pattern as required fields."""
    tool = next(t for t in MCP_TOOLS if t["name"] == "fs.search")
    assert "path" in tool["inputSchema"]["required"]
    assert "pattern" in tool["inputSchema"]["required"]
    assert "glob" in tool["inputSchema"]["properties"]
    assert "context" in tool["inputSchema"]["properties"]
    assert "ignore_case" in tool["inputSchema"]["properties"]
