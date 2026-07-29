"""v4.123.0 -- Runtime Compatibility Registry."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.extension_bridge.policy import classify_tool_risk  # noqa: E402
from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402
from arena.mcp.tool_runtime import handle_runtime_tool  # noqa: E402
from arena.workbench import runtime_compat as C  # noqa: E402


def _parsed(res):
    return json.loads(res["content"][0]["text"])


def test_runtime_compat_registered_and_safe():
    assert "runtime.compat" in {t["name"] for t in MCP_TOOLS}
    assert classify_tool_risk("runtime.compat") == "safe"


def test_runtime_compat_windows_matrix_known_limits():
    probe = {"ok": True, "runtimes": {
        "python3": {"available": True},
        "node": {"available": True},
        "go": {"available": True},
        "rustc": {"available": True, "linker_available": False, "diagnosis": "no linker"},
    }}
    out = C.build(probe, platform_name="Windows")
    rows = {(r["runtime"], r["sandbox"]): r for r in out["matrix"]}
    assert rows[("python3", "appcontainer")]["status"] == "supported"
    assert rows[("node", "appcontainer")]["status"] == "blocked"
    assert rows[("go", "appcontainer")]["status"] == "blocked"
    assert rows[("rustc", "appcontainer")]["status"] == "incomplete"
    assert rows[("python_project_deps", "appcontainer")]["status"] == "supported"
    assert "node.appcontainer" in {x["component"] for x in out["known_limits"]}


def test_runtime_compat_tool(monkeypatch):
    monkeypatch.setattr(C, "build", lambda: {"ok": True, "matrix": []})
    assert _parsed(handle_runtime_tool("runtime.compat", {}, ctx=object())) == {"ok": True, "matrix": []}
