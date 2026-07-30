"""MuMu wrappers and capability gap tracker."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena import capability_gaps  # noqa: E402
from arena.mcp.tool_mumu import handle_mumu_tool  # noqa: E402
from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402


def _text(res):
    return json.loads(res["content"][0]["text"])


def test_capability_gap_record_list_resolve(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    rec = capability_gaps.record(title="Need mumu wrapper", evidence={"err": "syntax"}, suggested_tool="mumu.shell")
    assert rec["ok"] is True
    gap_id = rec["gap"]["id"]
    listed = capability_gaps.list_gaps(status="open")
    assert listed["count"] == 1
    assert listed["gaps"][0]["suggested_tool"] == "mumu.shell"
    resolved = capability_gaps.resolve(gap_id=gap_id, resolution="implemented")
    assert resolved["ok"] is True
    assert capability_gaps.list_gaps(status="open")["count"] == 0


def test_mumu_tools_registered():
    names = {t["name"] for t in MCP_TOOLS}
    for name in ["mumu.version", "mumu.info", "mumu.launch", "mumu.shell", "mumu.adb", "mumu.screenshot", "capability_gap.record", "capability_gap.list", "capability_gap.resolve"]:
        assert name in names


def test_mumu_info_uses_cli_and_vmindex(monkeypatch):
    import arena.mcp.tool_mumu as tm

    monkeypatch.setattr(tm, "_cli", lambda: Path("/tmp/mumu-cli.exe"))
    monkeypatch.setattr(tm.Path, "exists", lambda self: True)
    calls = []

    def fake_run(argv, timeout=30):
        calls.append((argv, timeout))
        return {"ok": True, "returncode": 0, "argv": argv, "stdout": '{"android_version":"12.0"}', "stderr": ""}

    monkeypatch.setattr(tm, "_run", fake_run)
    payload = _text(handle_mumu_tool("mumu.info", {"vmindex": 2, "timeout": 9}, ctx=object()))
    assert payload["ok"] is True
    assert payload["json"]["android_version"] == "12.0"
    assert calls[0][0] == ["/tmp/mumu-cli.exe", "info", "--vmindex", "2"]
    assert calls[0][1] == 9


def test_mumu_shell_requires_cmd():
    payload = _text(handle_mumu_tool("mumu.shell", {}, ctx=object()))
    assert payload["ok"] is False
    assert payload["error"] == "cmd is required"
