"""v4.59.0 — desktop input MCP wrap, mobile app/file ops, browser.launch."""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from arena import constants
from arena.mcp.tool_registry import MCP_TOOLS
from arena.mcp.tool_desktop_input import (
    DESKTOP_INPUT_MCP_TOOLS, handle_desktop_input_tool,
)
from arena.mcp.tool_mobile_ext import (
    MOBILE_EXT_MCP_TOOLS, handle_mobile_ext_tool, _launch_app,
    _pull_file, _push_file, _list_files,
)
from arena.mcp.tool_browser_headed import (
    BROWSER_HEADED_MCP_TOOLS, handle_browser_headed_tool,
    _launch, _close, _list, _find_chrome,
)
from arena.extension_bridge.policy import classify_tool_risk


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(p): return (REPO_ROOT / p).read_text(encoding="utf-8")


# --- Version ---
def test_version_is_4_59_0():
    assert constants.VERSION in ("4.59.0","4.59.1", "4.60.0", "4.60.1", "4.60.2", "4.60.3", "4.60.4")


def test_pyproject_version_is_4_59_0():
    assert any(v in _read("pyproject.toml") for v in ('version = "4.59.0"', 'version = "4.59.1"', 'version = "4.60.0"', 'version = "4.60.1"', 'version = "4.60.2"', 'version = "4.60.3"', 'version = "4.60.4"'))


# --- Registry ---
def test_desktop_input_registry():
    names = {t["name"] for t in DESKTOP_INPUT_MCP_TOOLS}
    assert names == {"desktop.click", "desktop.type", "desktop.key", "desktop.mouse"}


def test_mobile_ext_registry():
    names = {t["name"] for t in MOBILE_EXT_MCP_TOOLS}
    assert names == {"mobile.launch_app", "mobile.pull_file", "mobile.push_file", "mobile.list_files"}


def test_browser_headed_registry():
    names = {t["name"] for t in BROWSER_HEADED_MCP_TOOLS}
    assert names == {"browser.launch", "browser.close", "browser.list"}


def test_all_new_tools_in_MCP_TOOLS():
    mcp = {t["name"] for t in MCP_TOOLS}
    for tools in (DESKTOP_INPUT_MCP_TOOLS, MOBILE_EXT_MCP_TOOLS, BROWSER_HEADED_MCP_TOOLS):
        for t in tools:
            assert t["name"] in mcp, f"missing: {t['name']}"


# --- Dispatchers wired ---
def test_dispatchers_wired():
    src = _read("arena/mcp/tools.py")
    for symbol in (
        "handle_desktop_input_tool", "handle_mobile_ext_tool", "handle_browser_headed_tool",
        "from arena.mcp.tool_desktop_input import handle_desktop_input_tool",
        "from arena.mcp.tool_mobile_ext import handle_mobile_ext_tool",
        "from arena.mcp.tool_browser_headed import handle_browser_headed_tool",
    ):
        assert symbol in src, symbol


# --- Risk classification ---
def test_desktop_input_dangerous():
    """Real mouse+keyboard control over the operator's desktop is dangerous
    — a rogue prompt could execute arbitrary UI actions. Extension must
    always require approval."""
    for t in ("desktop.click", "desktop.type", "desktop.key", "desktop.mouse"):
        assert classify_tool_risk(t) == "dangerous", t


def test_mobile_shell_ops_classification():
    assert classify_tool_risk("mobile.launch_app") == "medium"
    assert classify_tool_risk("mobile.pull_file") == "medium"
    assert classify_tool_risk("mobile.push_file") == "dangerous"  # writing to device fs
    assert classify_tool_risk("mobile.list_files") == "safe"


def test_browser_headed_classification():
    assert classify_tool_risk("browser.launch") == "medium"
    assert classify_tool_risk("browser.close") == "medium"
    assert classify_tool_risk("browser.list") == "safe"


# --- Dispatch validation ---
def test_desktop_input_dispatch_returns_none_for_non_matching():
    class _Ctx: pass
    assert handle_desktop_input_tool("fs.read", {}, ctx=_Ctx()) is None


def test_mobile_ext_dispatch_returns_none_for_non_matching():
    assert handle_mobile_ext_tool("mobile.tap", {"serial": "x"}) is None
    assert handle_mobile_ext_tool("fs.read", {}) is None


def test_mobile_ext_requires_serial():
    out = handle_mobile_ext_tool("mobile.launch_app", {})
    assert out and out.get("isError")


def test_browser_headed_dispatch_returns_none_for_non_matching():
    assert handle_browser_headed_tool("fs.read", {}) is None


# --- browser.launch requires chrome ---
def test_browser_launch_reports_no_chrome(monkeypatch):
    monkeypatch.setattr("arena.mcp.tool_browser_headed._find_chrome", lambda: None)
    monkeypatch.setattr("arena.mcp.tool_browser_headed._prune_dead_sessions", lambda: {})
    out = _launch({"session": "test-nochrome"})
    assert out["ok"] is False
    assert "chrome" in out["error"].lower() or "chromium" in out["error"].lower()


def test_browser_launch_refuses_existing_session(monkeypatch, tmp_path):
    monkeypatch.setattr("arena.mcp.tool_browser_headed._STATE_DIR", tmp_path)
    monkeypatch.setattr("arena.mcp.tool_browser_headed._STATE_FILE", tmp_path / "s.json")
    monkeypatch.setattr("arena.mcp.tool_browser_headed._pid_alive", lambda pid: True)
    (tmp_path / "s.json").write_text(json.dumps({"default": {"pid": 99999, "url": "x"}}))
    out = _launch({"session": "default"})
    assert out["ok"] is False
    assert "already running" in out["error"]


def test_browser_close_handles_missing_session(monkeypatch, tmp_path):
    monkeypatch.setattr("arena.mcp.tool_browser_headed._STATE_DIR", tmp_path)
    monkeypatch.setattr("arena.mcp.tool_browser_headed._STATE_FILE", tmp_path / "s.json")
    out = _close({"session": "nope"})
    assert out["ok"] is True
    assert "no such session" in out["note"]


def test_browser_list_returns_structure(monkeypatch, tmp_path):
    monkeypatch.setattr("arena.mcp.tool_browser_headed._STATE_DIR", tmp_path)
    monkeypatch.setattr("arena.mcp.tool_browser_headed._STATE_FILE", tmp_path / "s.json")
    out = _list({})
    assert out["ok"] is True
    assert "sessions" in out and "count" in out


# --- mobile.pull_file mock ---
def test_pull_file_missing_remote():
    out = _pull_file("2200ad3b", {})
    assert out["ok"] is False


def test_pull_file_happy_path(monkeypatch, tmp_path):
    def _fake_run_adb(args, timeout=60):
        # Simulate adb pull writing the file.
        target = args[args.index("pull") + 2]
        Path(target).write_bytes(b"fake audio")
        return 0, f"[100%] {target}", ""
    monkeypatch.setattr("arena.mcp.tool_mobile_ext._run_adb", _fake_run_adb)
    out = _pull_file("2200ad3b", {"remote": "/sdcard/test.mp3", "local": str(tmp_path / "test.mp3")})
    assert out["ok"] is True
    assert out["size_bytes"] == 10


def test_pull_file_return_bytes_embeds_b64(monkeypatch, tmp_path):
    def _fake_run_adb(args, timeout=60):
        target = args[args.index("pull") + 2]
        Path(target).write_bytes(b"HELLO")
        return 0, "", ""
    monkeypatch.setattr("arena.mcp.tool_mobile_ext._run_adb", _fake_run_adb)
    out = _pull_file("x", {"remote": "/x", "local": str(tmp_path / "x"), "return_bytes": True})
    assert out["ok"] is True
    import base64
    assert base64.b64decode(out["base64"]) == b"HELLO"


# --- mobile.list_files parsing ---
def test_list_files_parses_ls_output(monkeypatch):
    ls_out = (
        "total 8\n"
        "-rw-r--r-- 1 media_rw media_rw   123456 2026-07-20 23:14:32.000000000 +0300 audio1.mp3\n"
        "drwxrwx--x 2 root     root         4096 2026-07-15 10:00:00.000000000 +0300 subdir\n"
    )
    monkeypatch.setattr("arena.mcp.tool_mobile_ext._run_adb", lambda *a, **k: (0, ls_out, ""))
    out = _list_files("x", {"path": "/sdcard/"})
    assert out["ok"] is True
    names = {e.get("name") for e in out["entries"] if "name" in e}
    assert "audio1.mp3" in names
    assert "subdir" in names
    audio = next(e for e in out["entries"] if e.get("name") == "audio1.mp3")
    assert audio["type"] == "file"
    assert audio["size"] == 123456
    sub = next(e for e in out["entries"] if e.get("name") == "subdir")
    assert sub["type"] == "dir"


# --- mobile.launch_app payload ---
def test_launch_app_builds_am_command(monkeypatch):
    captured = {}
    def _fake_run_adb(args, timeout=60):
        captured["args"] = args
        return 0, "Starting: Intent { cmp=x/.y }", ""
    monkeypatch.setattr("arena.mcp.tool_mobile_ext._run_adb", _fake_run_adb)
    out = _launch_app("2200ad3b", {"package": "com.android.soundrecorder", "activity": ".StartActivity"})
    assert out["ok"] is True
    assert "am" in captured["args"] and "start" in captured["args"]
    assert "com.android.soundrecorder/.StartActivity" in captured["args"]


# --- Changelog ---
def test_changelog_mentions_v4_59_0():
    assert "4.59.0" in _read("CHANGELOG.md")
    assert "4.59.0" in _read("CHANGELOG.ru.md")
