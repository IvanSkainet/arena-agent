"""Tests for git.* MCP tools: git.status, git.diff, git.log, git.commit."""
import sys
import os
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.mcp.tool_git import handle_git_tool  # noqa: E402
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


def _init_repo(path: Path):
    """Initialize a git repo with an initial commit."""
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True, timeout=10)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(path), capture_output=True, timeout=5)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(path), capture_output=True, timeout=5)
    (path / "README.md").write_text("# Test Repo\n")
    subprocess.run(["git", "add", "-A"], cwd=str(path), capture_output=True, timeout=5)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=str(path), capture_output=True, timeout=5)


# ============================================================
# git.status tests
# ============================================================

def test_git_status_clean(tmp_path):
    """git.status shows clean working tree."""
    _init_repo(tmp_path)
    ctx = _MockCtx(tmp_path)
    result = handle_git_tool("git.status", {"path": str(tmp_path)}, ctx=ctx)
    assert result is not None
    text = result["content"][0]["text"]
    # "## main" (or master) with no file changes means clean
    assert "## " in text  # branch info present
    # No untracked/modified file markers
    assert "?? " not in text and " M " not in text and "A  " not in text


def test_git_status_with_changes(tmp_path):
    """git.status shows untracked/modified files."""
    _init_repo(tmp_path)
    (tmp_path / "new_file.py").write_text("x = 1\n")
    ctx = _MockCtx(tmp_path)
    result = handle_git_tool("git.status", {"path": str(tmp_path)}, ctx=ctx)
    assert result is not None
    text = result["content"][0]["text"]
    assert "new_file.py" in text


def test_git_status_not_a_repo(tmp_path):
    """git.status errors when not a git repo."""
    ctx = _MockCtx(tmp_path)
    result = handle_git_tool("git.status", {"path": str(tmp_path)}, ctx=ctx)
    assert result is not None
    assert result.get("isError") is True
    assert "not a git repository" in result["content"][0]["text"].lower()


def test_git_status_path_not_found(tmp_path):
    """git.status errors on non-existent path."""
    ctx = _MockCtx(tmp_path)
    result = handle_git_tool("git.status", {"path": str(tmp_path / "nonexistent")}, ctx=ctx)
    assert result is not None
    assert result.get("isError") is True


# ============================================================
# git.diff tests
# ============================================================

def test_git_diff_no_changes(tmp_path):
    """git.diff returns no differences when clean."""
    _init_repo(tmp_path)
    ctx = _MockCtx(tmp_path)
    result = handle_git_tool("git.diff", {"path": str(tmp_path)}, ctx=ctx)
    assert result is not None
    text = result["content"][0]["text"]
    assert "No differences" in text


def test_git_diff_with_changes(tmp_path):
    """git.diff shows unstaged changes."""
    _init_repo(tmp_path)
    (tmp_path / "README.md").write_text("# Modified\n")
    ctx = _MockCtx(tmp_path)
    result = handle_git_tool("git.diff", {"path": str(tmp_path)}, ctx=ctx)
    assert result is not None
    text = result["content"][0]["text"]
    assert "Modified" in text or "modified" in text.lower()


# ============================================================
# git.log tests
# ============================================================

def test_git_log_shows_commits(tmp_path):
    """git.log shows commit history."""
    _init_repo(tmp_path)
    ctx = _MockCtx(tmp_path)
    result = handle_git_tool("git.log", {"path": str(tmp_path)}, ctx=ctx)
    assert result is not None
    text = result["content"][0]["text"]
    assert "initial commit" in text


def test_git_log_limit(tmp_path):
    """git.log respects limit."""
    _init_repo(tmp_path)
    for i in range(5):
        (tmp_path / f"file{i}.py").write_text(f"# file {i}\n")
        subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), capture_output=True, timeout=5)
        subprocess.run(["git", "commit", "-m", f"commit {i}"], cwd=str(tmp_path), capture_output=True, timeout=5)
    ctx = _MockCtx(tmp_path)
    result = handle_git_tool("git.log", {"path": str(tmp_path), "limit": 2}, ctx=ctx)
    assert result is not None
    text = result["content"][0]["text"]
    lines = [l for l in text.strip().split("\n") if l.strip()]
    assert len(lines) <= 2


# ============================================================
# git.commit tests
# ============================================================

def test_git_commit_success(tmp_path):
    """git.commit stages and commits changes."""
    _init_repo(tmp_path)
    (tmp_path / "new.py").write_text("x = 1\n")
    ctx = _MockCtx(tmp_path)
    result = handle_git_tool("git.commit", {"path": str(tmp_path), "message": "add new.py"}, ctx=ctx)
    assert result is not None
    assert not result.get("isError"), f"expected success, got: {result}"
    text = result["content"][0]["text"]
    assert "Committed" in text


def test_git_commit_nothing_to_commit(tmp_path):
    """git.commit returns nothing to commit when clean."""
    _init_repo(tmp_path)
    ctx = _MockCtx(tmp_path)
    result = handle_git_tool("git.commit", {"path": str(tmp_path), "message": "empty"}, ctx=ctx)
    assert result is not None
    text = result["content"][0]["text"]
    assert "Nothing to commit" in text


def test_git_commit_missing_message(tmp_path):
    """git.commit errors when message is missing."""
    _init_repo(tmp_path)
    ctx = _MockCtx(tmp_path)
    result = handle_git_tool("git.commit", {"path": str(tmp_path)}, ctx=ctx)
    assert result is not None
    assert result.get("isError") is True
    assert "message" in result["content"][0]["text"].lower()


# ============================================================
# Registry tests
# ============================================================

def test_git_status_in_registry():
    names = [t["name"] for t in MCP_TOOLS]
    assert "git.status" in names


def test_git_diff_in_registry():
    names = [t["name"] for t in MCP_TOOLS]
    assert "git.diff" in names


def test_git_log_in_registry():
    names = [t["name"] for t in MCP_TOOLS]
    assert "git.log" in names


def test_git_commit_in_registry():
    names = [t["name"] for t in MCP_TOOLS]
    assert "git.commit" in names


def test_git_commit_schema():
    tool = next(t for t in MCP_TOOLS if t["name"] == "git.commit")
    assert "path" in tool["inputSchema"]["required"]
    assert "message" in tool["inputSchema"]["required"]


def test_git_returns_none_for_other_tools():
    """handle_git_tool returns None for non-git tools."""
    assert handle_git_tool("fs.read", {}, ctx=None) is None
    assert handle_git_tool("ping", {}, ctx=None) is None
