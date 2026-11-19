"""Regression oracles for the assembled stabilization review boundaries."""
from __future__ import annotations

import os
import stat

import pytest

from arena.files.fs_view_create import _view_bounds
from arena.mcp import standalone_tools
from arena.service.restart_common import RestartContext, render_template
from arena.tasks.process_worker import _write_worker_result


@pytest.mark.parametrize("relative", [".ssh", ".config/gh"])
def test_sensitive_selected_state_root_remains_blocked(tmp_path, monkeypatch, relative):
    state = tmp_path / relative
    state.mkdir(parents=True)
    target = state / "authorized_keys"
    target.write_text("must remain private")
    monkeypatch.setattr(standalone_tools, "agent_home", lambda: state)
    with pytest.raises(standalone_tools.PathJailError):
        standalone_tools._jail(str(target))
    result = standalone_tools.call_tool("fs.read", {"path": str(target)})
    assert result.get("isError") is True


@pytest.mark.parametrize("value", [True, False, 1.5, float("inf"), float("-inf"), float("nan")])
def test_invalid_view_numeric_bounds_are_validation_errors(value):
    with pytest.raises(ValueError, match="integers"):
        _view_bounds([value, 4], 10)


@pytest.mark.skipif(os.name == "nt", reason="POSIX inode mode contract; Windows uses deployment ACLs")
def test_existing_worker_result_is_made_private(tmp_path):
    result = tmp_path / "task.result.json"
    result.write_text("stale")
    result.chmod(0o666)
    _write_worker_result(result, "timeout")
    assert stat.S_IMODE(result.stat().st_mode) == 0o600
    assert '"timeout"' in result.read_text()


def test_tokenless_windows_restart_does_not_embed_unused_unicode_token():
    ctx = RestartContext(port=1234, sys_name="Windows", bridge_py="bridge.py",
                         token_file='C:\\токены\\unused"path.txt', task_name="Arena", pid=100)
    rendered = render_template("@echo off\nnssm restart Arena\n", ctx)
    assert rendered.isascii()
    assert "ARENA_RESTART_TOKEN_FILE" not in rendered


def test_executable_copy_dry_run_does_not_stat_a_missing_output(tmp_path, monkeypatch):
    from setuptools.dist import Distribution

    from arena.build_tools import BuildWithTools

    source = tmp_path / "bin"
    source.mkdir()
    (source / "sd-exec").write_text("fixture")
    distribution = Distribution()
    distribution.dry_run = True
    command = BuildWithTools(distribution)
    command.dry_run = True
    monkeypatch.setattr(command, "copy_file", lambda *args: None)
    destination = tmp_path / "generated"
    command._copy_tools(source, destination)
    assert not (destination / "sd-exec").exists()
