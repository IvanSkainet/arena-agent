"""Tests for fs.edit MCP tool and PATCH /v1/fs/edit REST endpoint.

Covers:
  - MCP fs.edit: success, replace_all, not found, multiple matches, empty old_text,
    blocked file, file not found, no-op (old==new)
  - MCP safe editor companions: fs.edit_apply, fs.edit_rollback registration
  - REST PATCH /v1/fs/edit and safe-editor companion routes
  - validate_edit_target: path traversal, blocked files, bridge itself, missing file
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.files.sandbox import validate_edit_target, _EDIT_BLOCKED_BASENAMES  # noqa: E402
from arena.mcp.tool_fs import handle_fs_tool  # noqa: E402


class _MockCtx:
    """Minimal ctx for handle_fs_tool — under_root checks against home_dir."""

    def __init__(self, home_dir):
        self._home = Path(home_dir).resolve()

    def under_root(self, p, home):
        try:
            Path(p).resolve().relative_to(self._home)
            return True
        except (ValueError, TypeError):
            return False


# ============================================================
# MCP fs.edit tool tests (via handle_fs_tool directly)
# ============================================================

def test_mcp_fs_edit_success(tmp_path):
    """fs.edit replaces unique old_text with new_text."""
    f = tmp_path / "test.py"
    f.write_text("def hello():\n    print('foo()')\n    return 42\n")
    ctx = _MockCtx(tmp_path)
    result = handle_fs_tool("fs.edit", {"path": str(f), "old_text": "foo()", "new_text": "bar()"}, ctx=ctx)
    assert result is not None
    assert not result.get("isError"), f"expected success, got: {result}"
    assert "1 replacement" in result["content"][0]["text"]
    assert "bar()" in f.read_text()
    assert "foo()" not in f.read_text()


def test_mcp_fs_edit_replace_all(tmp_path):
    """fs.edit with replace_all=true replaces all occurrences."""
    f = tmp_path / "test.py"
    f.write_text("foo()\nfoo()\nfoo()\n")
    ctx = _MockCtx(tmp_path)
    result = handle_fs_tool("fs.edit", {"path": str(f), "old_text": "foo()", "new_text": "bar()", "replace_all": True}, ctx=ctx)
    assert result is not None
    assert not result.get("isError"), f"expected success, got: {result}"
    assert "3 replacement" in result["content"][0]["text"]
    content = f.read_text()
    assert content.count("bar()") == 3
    assert "foo()" not in content


def test_mcp_fs_edit_multiple_matches_without_replace_all(tmp_path):
    """fs.edit errors when old_text matches multiple times and replace_all is not set."""
    f = tmp_path / "test.py"
    f.write_text("foo()\nfoo()\nfoo()\n")
    ctx = _MockCtx(tmp_path)
    result = handle_fs_tool("fs.edit", {"path": str(f), "old_text": "foo()", "new_text": "bar()"}, ctx=ctx)
    assert result is not None
    assert result.get("isError") is True
    assert "matches 3 times" in result["content"][0]["text"]
    # File should be unchanged
    assert f.read_text() == "foo()\nfoo()\nfoo()\n"


def test_mcp_fs_edit_old_text_not_found(tmp_path):
    """fs.edit errors when old_text is not in the file."""
    f = tmp_path / "test.py"
    f.write_text("hello world\n")
    ctx = _MockCtx(tmp_path)
    result = handle_fs_tool("fs.edit", {"path": str(f), "old_text": "xyz", "new_text": "abc"}, ctx=ctx)
    assert result is not None
    assert result.get("isError") is True
    assert "not found" in result["content"][0]["text"]


def test_mcp_fs_edit_file_not_found(tmp_path):
    """fs.edit errors when the file does not exist."""
    ctx = _MockCtx(tmp_path)
    result = handle_fs_tool("fs.edit", {"path": str(tmp_path / "nonexistent.py"), "old_text": "a", "new_text": "b"}, ctx=ctx)
    assert result is not None
    assert result.get("isError") is True
    assert "file not found" in result["content"][0]["text"]


def test_mcp_fs_edit_empty_old_text(tmp_path):
    """fs.edit errors when old_text is empty."""
    f = tmp_path / "test.py"
    f.write_text("hello\n")
    ctx = _MockCtx(tmp_path)
    result = handle_fs_tool("fs.edit", {"path": str(f), "old_text": "", "new_text": "b"}, ctx=ctx)
    assert result is not None
    assert result.get("isError") is True
    assert "missing or empty" in result["content"][0]["text"]


def test_mcp_fs_edit_noop_when_old_equals_new(tmp_path):
    """fs.edit returns no-op message when old_text == new_text."""
    f = tmp_path / "test.py"
    f.write_text("foo()\n")
    ctx = _MockCtx(tmp_path)
    result = handle_fs_tool("fs.edit", {"path": str(f), "old_text": "foo()", "new_text": "foo()"}, ctx=ctx)
    assert result is not None
    assert not result.get("isError"), f"expected success, got: {result}"
    assert "no changes" in result["content"][0]["text"]
    # File should be unchanged
    assert f.read_text() == "foo()\n"


def test_mcp_fs_edit_blocked_file(tmp_path):
    """fs.edit blocks editing sensitive files (token.txt, .env, etc.)."""
    f = tmp_path / "token.txt"
    f.write_text("secret-token-here\n")
    ctx = _MockCtx(tmp_path)
    result = handle_fs_tool("fs.edit", {"path": str(f), "old_text": "secret", "new_text": "newsecret"}, ctx=ctx)
    assert result is not None
    assert result.get("isError") is True
    assert "BLOCKED" in result["content"][0]["text"]
    assert "token.txt" in result["content"][0]["text"]
    # File should be unchanged
    assert f.read_text() == "secret-token-here\n"


def test_mcp_fs_edit_in_tool_registry():
    """fs.edit is registered in MCP_TOOLS list."""
    from arena.mcp.tool_registry import MCP_TOOLS
    names = [t["name"] for t in MCP_TOOLS]
    assert "fs.edit" in names


def test_mcp_fs_edit_schema_has_required_fields():
    """fs.edit input schema has path, old_text, new_text as required."""
    from arena.mcp.tool_registry import MCP_TOOLS
    tool = next(t for t in MCP_TOOLS if t["name"] == "fs.edit")
    schema = tool["inputSchema"]
    assert "path" in schema["required"]
    assert "old_text" in schema["required"]
    assert "new_text" in schema["required"]
    assert "replace_all" in schema["properties"]
    assert "preview" in schema["properties"]
    assert schema["properties"]["replace_all"]["type"] == "boolean"
    names = [t["name"] for t in MCP_TOOLS]
    assert "fs.edit_apply" in names
    assert "fs.edit_rollback" in names


# ============================================================
# validate_edit_target tests (sandbox layer)
# ============================================================

def test_validate_edit_target_success(tmp_path):
    """validate_edit_target returns path for a valid existing file."""
    home = tmp_path / "home"; home.mkdir()
    f = home / "file.py"; f.write_text("x")
    bridge = home / "bridge.py"; bridge.write_text("x")
    path, err, status = validate_edit_target("file.py", root=home, home=home, bridge_py=bridge)
    assert err is None and status == 200 and path == f


def test_validate_edit_target_blocks_traversal(tmp_path):
    """validate_edit_target blocks path traversal."""
    home = tmp_path / "home"; home.mkdir()
    bridge = home / "bridge.py"; bridge.write_text("x")
    path, err, status = validate_edit_target("../x", root=home, home=home, bridge_py=bridge)
    assert err == "path traversal not allowed" and status == 400


def test_validate_edit_target_blocks_bridge_itself(tmp_path):
    """validate_edit_target blocks editing the bridge binary itself."""
    home = tmp_path / "home"; home.mkdir()
    bridge = home / "unified_bridge.py"; bridge.write_text("x")
    path, err, status = validate_edit_target("unified_bridge.py", root=home, home=home, bridge_py=bridge)
    assert err == "cannot edit the bridge itself" and status == 403


def test_validate_edit_target_blocks_sensitive_files(tmp_path):
    """validate_edit_target blocks token.txt, .env, SSH keys, etc."""
    home = tmp_path / "home"; home.mkdir()
    bridge = home / "bridge.py"; bridge.write_text("x")
    for blocked_name in ["token.txt", ".env", "id_rsa", "users.json"]:
        f = home / blocked_name; f.write_text("secret")
        path, err, status = validate_edit_target(blocked_name, root=home, home=home, bridge_py=bridge)
        assert err is not None and status == 403, f"expected block for {blocked_name}, got: {err}"
        assert "not allowed" in err


def test_validate_edit_target_file_not_found(tmp_path):
    """validate_edit_target returns 404 for non-existent file."""
    home = tmp_path / "home"; home.mkdir()
    bridge = home / "bridge.py"; bridge.write_text("x")
    path, err, status = validate_edit_target("missing.py", root=home, home=home, bridge_py=bridge)
    assert err == "file not found" and status == 404


def test_edit_blocked_basenames_set_contents():
    """_EDIT_BLOCKED_BASENAMES contains expected sensitive files."""
    assert "token.txt" in _EDIT_BLOCKED_BASENAMES
    assert ".env" in _EDIT_BLOCKED_BASENAMES
    assert "id_rsa" in _EDIT_BLOCKED_BASENAMES
    assert "users.json" in _EDIT_BLOCKED_BASENAMES


# ============================================================
# REST PATCH /v1/fs/edit route registration test
# ============================================================

def test_rest_fs_edit_route_registered():
    """PATCH /v1/fs/edit and safe-editor companion routes are registered in the app."""
    app = ub.make_app({"token": "test", "profile": "owner-shell", "root": "/tmp", "active_exec": 0, "max_concurrent": 3, "audit": "audit"})
    paths = {(r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter")) for r in app.router.routes()}
    assert ("PATCH", "/v1/fs/edit") in paths, f"PATCH /v1/fs/edit not in routes: {paths}"
    assert ("POST", "/v1/fs/edit/apply") in paths
    assert ("POST", "/v1/fs/edit/rollback") in paths


def test_file_handlers_have_fs_edit_fields():
    """FileHandlers dataclass has safe-edit fields."""
    from arena.files.handlers import FileHandlers
    import dataclasses
    fields = {f.name for f in dataclasses.fields(FileHandlers)}
    assert {"fs_edit", "fs_edit_apply", "fs_edit_rollback"}.issubset(fields), f"missing fields: {fields}"
