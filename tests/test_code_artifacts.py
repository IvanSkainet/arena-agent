"""v4.109.0 -- persisted Code Workbench artifacts."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.extension_bridge.policy import classify_tool_risk  # noqa: E402
from arena.mcp.tool_code_artifact import handle_code_artifact_tool  # noqa: E402
from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402
from arena.workbench import artifacts  # noqa: E402


def _parsed(res):
    return json.loads(res["content"][0]["text"])


def test_artifact_store_persist_info_read(tmp_path, monkeypatch):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    scratch = tmp_path / "scratch"
    (scratch / "out").mkdir(parents=True)
    (scratch / "out" / "a.txt").write_text("hello", encoding="utf-8")
    items = [{"path": "out/a.txt", "bytes": 5, "text": "hello", "truncated": False}]
    persisted = artifacts.persist_run("abc123", scratch, items)
    assert persisted[0]["download_url"].endswith("/out/a.txt")
    assert artifacts.run_info("abc123")["ok"] is True
    assert artifacts.read_artifact("abc123", "out/a.txt")["text"] == "hello"


def test_artifact_mcp_tools_registered_and_safe(tmp_path, monkeypatch):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    names = {t["name"] for t in MCP_TOOLS}
    assert {"code_run.info", "code_artifact.read"} <= names
    assert classify_tool_risk("code_run.info") == "safe"
    assert classify_tool_risk("code_artifact.read") == "safe"
    out = _parsed(handle_code_artifact_tool("code_run.info", {"run_id": "missing"}, ctx=object()))
    assert out["ok"] is False



def test_code_artifact_routes_registered():
    from arena.route_registry.registry import ROUTES
    paths = {(m, p) for m, p, *_ in ROUTES}
    assert ("GET", "/v1/code/runs/{run_id}") in paths
    assert ("GET", "/v1/code/runs/{run_id}/artifacts/{path:.*}") in paths


def test_resource_handlers_include_code_artifact_fields():
    from dataclasses import fields

    from arena.resources.handlers import ResourceHandlers
    names = {f.name for f in fields(ResourceHandlers)}
    assert "code_run_info" in names
    assert "code_artifact_download" in names
