"""v4.83.0 — adb discovery for the v4.59.0 mobile.* MCP tools.

Scenario drive ("voice memo -> transcription") found that
``mobile.launch_app`` / ``pull_file`` / ``push_file`` / ``list_files``
all failed with "adb not found on PATH" on hosts where adb is installed
under the Android SDK platform-tools dir but NOT on the bridge process
PATH — while ``mobile.ui`` / ``mobile.shell`` (which use the robust
``arena.mobile.adb.find_adb``) worked fine.

The fix routes these tools through the same ``find_adb`` discovery.
These tests pin that wiring so a regression back to ``shutil.which``
(which is PATH-only) is caught before it ships.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.mcp import tool_mobile_ext as ext


def test_adb_path_delegates_to_mobile_discovery(monkeypatch):
    # Must reflect whatever find_adb resolves (explicit SDK candidates),
    # not the PATH-only shutil.which result.
    monkeypatch.setattr(ext, "_find_adb",
                        lambda: "/fake/sdk/platform-tools/adb")
    assert ext._adb_path() == "/fake/sdk/platform-tools/adb"

    monkeypatch.setattr(ext, "_find_adb", lambda: None)
    assert ext._adb_path() is None


def test_run_adb_missing_adb_error_is_actionable(monkeypatch):
    monkeypatch.setattr(ext, "_find_adb", lambda: None)
    rc, out, err = ext._run_adb(["devices"])
    assert rc == -1
    assert out == ""
    assert "adb not found" in err
    # The error must carry the platform-specific install hint so the
    # agent (or user) knows how to fix it, not just that it failed.
    assert any(tok in err for tok in (
        "platform-tools", "developer.android.com", "apt", "brew",
        "winget", "scoop", "pacman",
    ))
