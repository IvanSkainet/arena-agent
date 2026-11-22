"""#515: looking for MCP pid files, at exit or at start, does not create the directory they would live in."""
from __future__ import annotations

import json

import pytest

import arena.mcp_client.client as mcp


class _Process:
    pid = 4242


class _Client:
    """A started server, as far as pid-file recording can tell."""

    proc = _Process()
    command = ["server"]


@pytest.fixture(name="manager")
def _manager(tmp_path):
    """A manager whose home does not exist yet."""
    return mcp.McpClientManager(tmp_path / "home" / "mcp" / "mcp.json")


def _home(manager) -> object:
    return manager.config_path.parent.parent


def test_stopping_everything_creates_nothing(manager):
    """The exit path: no server was ever started."""
    manager.stop_all()
    assert not _home(manager).exists()


def test_the_exit_handler_creates_nothing(manager, monkeypatch):
    """What the interpreter runs on its way out."""
    monkeypatch.setattr(mcp, "_MANAGER", manager)
    mcp._atexit_stop_all()
    assert not _home(manager).exists()


def test_the_orphan_scan_creates_nothing(manager):
    """The start path: nothing to scan is not a reason to write."""
    assert manager.reap_orphans()["reaped"] == []
    assert not _home(manager).exists()


def test_clearing_a_pid_file_that_is_not_there_creates_nothing(manager):
    """Stopping one server that left no record."""
    manager.stop("absent")
    assert not _home(manager).exists()


def test_recording_a_server_still_creates_the_directory(manager):
    """The one caller that needs it."""
    manager._record_pidfile("files", _Client())
    record = json.loads((manager.config_path.parent / "run" / "files.json").read_text(encoding="utf-8"))
    assert record["pid"] == 4242


def test_stopping_everything_still_clears_the_records(manager):
    """The clean-up the directory listing is there for."""
    manager._record_pidfile("files", _Client())
    manager._record_pidfile("search", _Client())
    manager.stop_all()
    assert list((manager.config_path.parent / "run").iterdir()) == []
