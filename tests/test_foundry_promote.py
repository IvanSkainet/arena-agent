"""v4.121.0 -- promote project/run experiments into tools."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.extension_bridge.policy import classify_tool_risk  # noqa: E402
from arena.foundry import tools as F  # noqa: E402
from arena.mcp.tool_code_artifact import handle_code_artifact_tool  # noqa: E402
from arena.mcp.tool_code_project import handle_code_project_tool  # noqa: E402
from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402
from arena.workbench import artifacts, projects  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_custom_cache():
    import arena.mcp.custom_tools as C
    C._reset_cache()
    yield
    C._reset_cache()


def _parsed(res):
    return json.loads(res["content"][0]["text"])


def _recipe():
    return {
        "tool_name": "promoted_demo",
        "description": "Promoted demo tool",
        "input_schema": {"properties": {"value": {"type": "integer"}}, "required": ["value"]},
        "run": {"lang": "python3", "entry": "main.py", "argv": ["{value}"], "artifacts": ["out/result.json"], "timeout": 30},
        "tests": [{"name": "value-5", "args": {"value": 5}, "expect": {"ok": True, "stdout_contains": "VALUE=5"}}],
    }


def test_promote_tools_registered_and_risk():
    names = {t["name"] for t in MCP_TOOLS}
    assert {"code_project.promote_tool", "code_run.promote_tool"} <= names
    assert classify_tool_risk("code_project.promote_tool") == "medium"
    assert classify_tool_risk("code_run.promote_tool") == "medium"


def test_promote_project_writes_manifest_and_publishes(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    import arena.mcp.custom_tools as C
    C._reset_cache()
    projects.create("p", [{"path": "main.py", "content": "print('VALUE=5')\n"}], overwrite=True)
    monkeypatch.setattr(F.projects, "run", lambda name, **kwargs: {"ok": True, "stdout": "VALUE=5\n", "artifacts": []})
    out = F.promote_project("p", overwrite_manifest=True, **_recipe())
    assert out["ok"] is True
    assert out["tool"] == "custom.promoted_demo"
    manifest = projects.read("p", F.DEFAULT_MANIFEST)
    assert manifest["ok"] is True
    assert "promoted_from" in manifest["text"]
    assert any(t["name"] == "custom.promoted_demo" for t in C.list_tools())


def test_promote_run_requires_existing_run_and_records_provenance(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    import arena.mcp.custom_tools as C
    C._reset_cache()
    projects.create("p", [{"path": "main.py", "content": "print('VALUE=5')\n"}], overwrite=True)
    scratch = tmp_path / "scratch"
    (scratch / "out").mkdir(parents=True)
    (scratch / "out" / "result.json").write_text('{"ok":true}', encoding="utf-8")
    artifacts.persist_run("run123", scratch, [{"path": "out/result.json", "text": '{"ok":true}'}])
    monkeypatch.setattr(F.projects, "run", lambda name, **kwargs: {"ok": True, "stdout": "VALUE=5\n", "artifacts": []})
    out = F.promote_run("run123", project="p", overwrite_manifest=True, **_recipe())
    assert out["ok"] is True
    assert out["source_run"]["run_id"] == "run123"
    manifest = json.loads(projects.read("p", F.DEFAULT_MANIFEST)["text"])
    assert manifest["promoted_from"]["kind"] == "run"
    assert manifest["promoted_from"]["run_id"] == "run123"


def test_promote_mcp_handlers(monkeypatch):
    monkeypatch.setattr(F, "promote_project", lambda project, **kw: {"ok": True, "project": project, "tool": "custom.p"})
    monkeypatch.setattr(F, "promote_run", lambda run_id, **kw: {"ok": True, "run_id": run_id, "tool": "custom.r"})
    p = _parsed(handle_code_project_tool("code_project.promote_tool", {"name": "p", **_recipe()}, ctx=object()))
    r = _parsed(handle_code_artifact_tool("code_run.promote_tool", {"run_id": "rid", "project": "p", **_recipe()}, ctx=object()))
    assert p["tool"] == "custom.p"
    assert r["tool"] == "custom.r"
