"""A JSON `null` path must be refused, not crash the handler.

`args.get("path", "")` looks like it defaults to `""`, but the default only
applies when the key is *absent*. A body of `{"path": null}` returns None, and
None flowed straight into `os.path.expanduser`, which raises

    TypeError: expected str, bytes or os.PathLike object, not NoneType

from inside the tool. Five call sites had the shape -- fs.read/write/list,
fs.search, fs tree diff and the git tools -- all of them reachable from an MCP
client, which means any caller could turn a typo into a stack trace instead of
an error response.

Found by pyrefly reporting `expanduser` called with `Any | None`. The tests
below send the hostile value through the real handlers, because "the type looks
fine" was exactly the state that shipped.
"""
from __future__ import annotations

import ast
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from arena.mcp.tool_fs import handle_fs_tool  # noqa: E402
from arena.mcp.tool_fs_search import handle_fs_search_tool  # noqa: E402
from arena.mcp.tool_git import handle_git_tool  # noqa: E402


def _ctx():
    return types.SimpleNamespace(under_root=lambda a, b: True)


def _is_error(result) -> bool:
    return isinstance(result, dict) and bool(result.get("isError"))


@pytest.mark.parametrize("tool", ["fs.read", "fs.write", "fs.list"])
def test_fs_tools_refuse_a_null_path(tool):
    args = {"path": None}
    if tool == "fs.write":
        args["content"] = "x"
    result = handle_fs_tool(tool, args, ctx=_ctx())
    assert _is_error(result), f"{tool} accepted a null path: {result}"


def test_fs_search_refuses_a_null_path():
    result = handle_fs_search_tool("fs.search", {"path": None, "query": "x"}, ctx=_ctx())
    assert result is None or _is_error(result)


def test_git_tools_refuse_a_null_path():
    result = handle_git_tool("git.status", {"path": None}, ctx=_ctx())
    assert result is None or _is_error(result)


def test_tree_diff_refuses_null_path_pairs():
    from arena.mcp.tool_fs_tree_diff import _handle_fs_diff

    for args in ({"path_a": None, "path_b": "/tmp/b"},
                 {"path_a": "/tmp/a", "path_b": None},
                 {"path_a": None, "path_b": None}):
        result = _handle_fs_diff(dict(args), _ctx())
        assert _is_error(result), f"accepted {args}: {result}"


def test_an_absent_key_still_behaves_the_same():
    """The fix must not change the missing-argument path."""
    absent = handle_fs_tool("fs.read", {}, ctx=_ctx())
    null = handle_fs_tool("fs.read", {"path": None}, ctx=_ctx())
    assert _is_error(absent) and _is_error(null)
    assert absent["content"][0]["text"] == null["content"][0]["text"]


def test_no_handler_reintroduces_the_get_with_default_shape():
    """`x.get(k, default)` piped into a None-rejecting sink is the bug."""
    sinks = {"expanduser", "abspath", "realpath", "basename", "dirname",
             "quote", "unquote"}
    offenders: list[str] = []
    for path in sorted((REPO / "arena").rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr not in sinks or not node.args:
                continue
            arg = node.args[0]
            if (isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute)
                    and arg.func.attr == "get" and len(arg.args) == 2):
                offenders.append(
                    f"{path.relative_to(REPO)}:{node.lineno} {ast.unparse(node)[:70]}")
    assert offenders == [], (
        "`.get(key, default)` returns None when the key exists and holds null; "
        f"use `or` instead at: {offenders}"
    )
