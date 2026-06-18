"""MCP git tools: git.status, git.diff, git.log, git.commit.

Git integration for AI agents — allows checking repo status, viewing
diffs, reading commit history, and creating commits without leaving
the MCP protocol.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from arena.files.sandbox import SENSITIVE_FILE_BASENAMES
from arena.mcp.tool_utils import text_content

_MCP_BLOCKED_FILES = SENSITIVE_FILE_BASENAMES


def _validate_repo_path(path_str: str, ctx) -> tuple[Path | None, dict[str, Any] | None]:
    """Validate that path is inside home directory."""
    if not path_str:
        return None, {"isError": True, "content": [{"type": "text", "text": "ERROR: missing 'path' argument"}]}
    resolved = Path(path_str).resolve()
    home = Path.home().resolve()
    if not ctx.under_root(resolved, home):
        return None, {"isError": True, "content": [{"type": "text", "text": "BLOCKED: path outside home directory"}]}
    return resolved, None


def _run_git(repo_path: Path, args: list[str], timeout: int = 15) -> tuple[int, str, str]:
    """Run a git command in repo_path. Returns (exit_code, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "git command timed out"
    except Exception as e:
        return -2, "", str(e)


def handle_git_tool(name: str, args: dict[str, Any], *, ctx) -> dict[str, Any] | None:
    """Handle git.status, git.diff, git.log, git.commit MCP tools."""
    if name not in {"git.status", "git.diff", "git.log", "git.commit"}:
        return None

    path_str = os.path.expanduser(args.get("path", ""))
    path, err = _validate_repo_path(path_str, ctx)
    if err:
        return err

    if not path.exists():
        return {"isError": True, "content": [{"type": "text", "text": f"ERROR: path not found: {path}"}]}
    if not path.is_dir():
        return {"isError": True, "content": [{"type": "text", "text": f"ERROR: path is not a directory: {path}"}]}

    # Check it's a git repo
    code, _, _ = _run_git(path, ["rev-parse", "--is-inside-work-tree"])
    if code != 0:
        return {"isError": True, "content": [{"type": "text", "text": f"ERROR: not a git repository: {path}"}]}

    if name == "git.status":
        return _handle_git_status(path, args)
    if name == "git.diff":
        return _handle_git_diff(path, args)
    if name == "git.log":
        return _handle_git_log(path, args)
    if name == "git.commit":
        return _handle_git_commit(path, args)
    return None


def _handle_git_status(path: Path, args: dict[str, Any]) -> dict[str, Any]:
    """Show git status (porcelain + branch info)."""
    short = bool(args.get("short", False))
    fmt = ["--porcelain"] if short else ["--porcelain=v1", "-b"]
    code, stdout, stderr = _run_git(path, ["status"] + fmt)
    if code != 0:
        return {"isError": True, "content": [{"type": "text", "text": f"ERROR: git status failed: {stderr}"}]}
    return text_content(stdout.strip() if stdout.strip() else "Working tree clean")


def _handle_git_diff(path: Path, args: dict[str, Any]) -> dict[str, Any]:
    """Show git diff (staged, unstaged, or specific commit)."""
    staged = bool(args.get("staged", False))
    commit = args.get("commit", "")

    git_args = ["diff"]
    if staged:
        git_args.append("--cached")
    if commit:
        git_args.append(commit)

    code, stdout, stderr = _run_git(path, git_args, timeout=30)
    if code != 0:
        return {"isError": True, "content": [{"type": "text", "text": f"ERROR: git diff failed: {stderr}"}]}
    return text_content(stdout.strip() if stdout.strip() else "No differences")


def _handle_git_log(path: Path, args: dict[str, Any]) -> dict[str, Any]:
    """Show git log (oneline, last N commits)."""
    limit = min(int(args.get("limit", 10)), 100)
    oneline = bool(args.get("oneline", True))

    git_args = ["log"]
    if oneline:
        git_args.append("--oneline")
    git_args.append(f"-{limit}")

    code, stdout, stderr = _run_git(path, git_args, timeout=15)
    if code != 0:
        return {"isError": True, "content": [{"type": "text", "text": f"ERROR: git log failed: {stderr}"}]}
    return text_content(stdout.strip() if stdout.strip() else "No commits")


def _handle_git_commit(path: Path, args: dict[str, Any]) -> dict[str, Any]:
    """Stage all changes and create a commit."""
    message = args.get("message", "")
    add_all = bool(args.get("add_all", True))

    if not message:
        return {"isError": True, "content": [{"type": "text", "text": "ERROR: missing 'message' argument"}]}

    # Stage changes
    if add_all:
        code, _, stderr = _run_git(path, ["add", "-A"])
        if code != 0:
            return {"isError": True, "content": [{"type": "text", "text": f"ERROR: git add failed: {stderr}"}]}

    # Check if there's anything to commit
    code, stdout, _ = _run_git(path, ["diff", "--cached", "--name-only"])
    if not stdout.strip():
        return text_content("Nothing to commit (no staged changes)")

    # Commit
    code, stdout, stderr = _run_git(path, ["commit", "-m", message])
    if code != 0:
        return {"isError": True, "content": [{"type": "text", "text": f"ERROR: git commit failed: {stderr}"}]}

    return text_content(f"Committed: {stdout.strip()}")
