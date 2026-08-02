"""v4.120.0 -- Tool Foundry v1."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.extension_bridge.policy import classify_tool_risk  # noqa: E402
from arena.foundry import tools as F  # noqa: E402
from arena.mcp.tool_foundry import handle_foundry_tool  # noqa: E402
from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402
from arena.mcp.tools import McpToolContext, make_mcp_tool_runtime  # noqa: E402
from arena.workbench import projects  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_custom_cache():
    import arena.mcp.custom_tools as C
    C._reset_cache()
    yield
    C._reset_cache()


def _parsed(res):
    return json.loads(res["content"][0]["text"])


def _manifest(name="fib_tool"):
    return {
        "name": name,
        "description": "Return a Fibonacci value from a Workbench project.",
        "input_schema": {"properties": {"n": {"type": "integer"}}, "required": ["n"]},
        "run": {"lang": "python3", "entry": "main.py", "argv": ["{n}"], "artifacts": ["out/result.json"], "timeout": 30},
        "tests": [{"name": "fib-7", "args": {"n": 7}, "expect": {"ok": True, "stdout_contains": "FIB=13", "artifact_contains": {"out/result.json": "13"}}}],
    }


def test_foundry_tools_registered_and_risk():
    names = {t["name"] for t in MCP_TOOLS}
    assert {"tool_foundry.list", "tool_foundry.validate", "tool_foundry.publish"} <= names
    assert classify_tool_risk("tool_foundry.list") == "safe"
    assert classify_tool_risk("tool_foundry.validate") == "safe"
    assert classify_tool_risk("tool_foundry.publish") == "medium"


def test_validate_manifest_runs_tests(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    projects.create("fib", [{"path": F.DEFAULT_MANIFEST, "content": json.dumps(_manifest())}], overwrite=True)

    def fake_run(name, **kwargs):
        assert name == "fib"
        assert kwargs["argv"] == ["7"]
        return {"ok": True, "stdout": "FIB=13\n", "run_id": "run1", "artifacts": [{"path": "out/result.json", "text": '{"fib":13}'}]}

    monkeypatch.setattr(F.projects, "run", fake_run)
    out = F.validate("fib")
    assert out["ok"] is True
    assert out["tool"] == "custom.fib_tool"
    assert out["tests"][0]["ok"] is True


def test_publish_creates_callable_custom_tool(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    # Reset custom-tool cache after changing ARENA_AGENT_HOME.
    import arena.mcp.custom_tools as C
    C._reset_cache()
    projects.create("fib", [{"path": F.DEFAULT_MANIFEST, "content": json.dumps(_manifest("fib_pub"))}], overwrite=True)
    monkeypatch.setattr(F.projects, "run", lambda name, **kwargs: {"ok": True, "stdout": "FIB=13\n", "artifacts": [{"path": "out/result.json", "text": "13"}]})
    out = F.publish("fib")
    assert out["ok"] is True
    assert out["tool"] == "custom.fib_pub"
    listed = C.list_tools()
    assert any(t["name"] == "custom.fib_pub" for t in listed)
    assert C.risk_of("custom.fib_pub") == "dangerous"  # wraps code_project.run


def test_foundry_mcp_tool(monkeypatch):
    monkeypatch.setattr(F, "list_candidates", lambda: {"ok": True, "count": 1})
    monkeypatch.setattr(F, "validate", lambda project, manifest_path, run_tests=True: {"ok": True, "project": project, "run_tests": run_tests})
    monkeypatch.setattr(F, "publish", lambda project, manifest_path, run_tests=True: {"ok": True, "tool": "custom.x"})
    assert _parsed(handle_foundry_tool("tool_foundry.list", {}, ctx=object()))["count"] == 1
    assert _parsed(handle_foundry_tool("tool_foundry.validate", {"project": "p", "run_tests": False}, ctx=object()))["run_tests"] is False
    assert _parsed(handle_foundry_tool("tool_foundry.publish", {"project": "p"}, ctx=object()))["tool"] == "custom.x"


def test_runtime_tools_list_includes_published_custom(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    import arena.mcp.custom_tools as C
    C._reset_cache()
    C.create_tool("hello_foundry", "hello", {"properties": {}, "required": []}, call={"tool": "exec.echo", "args": {"text": "hi"}})
    ctx = McpToolContext(
        version="test", bin_dir=tmp_path, bridge_dir=tmp_path, reports_dir=tmp_path,
        subprocess_kwargs=lambda: {}, blocked_reason=lambda c: None, first_word=lambda c: c.split()[0] if c.split() else "",
        cautious_allow=set(), under_root=lambda p, r: True, write_fact=lambda f: None, load_facts=lambda **kw: [],
        recall_sync=lambda **kw: {}, recall_digest_sync=lambda **kw: {}, audit=lambda e: None, app_config=lambda: {},
        common_status=lambda cfg: {}, build_plan=lambda **kw: {}, file_watch_list_sync=lambda: {}, file_watch_add_sync=lambda **kw: {},
        file_watch_remove_sync=lambda p: {}, react_sync=lambda **kw: {}, reflect_sync=lambda **kw: {}, utc_now=lambda: "now",
        skills_list_sync_with_cache=lambda: {}, skills_run_sync=lambda **kw: {}, play_beep_sync=lambda a,b,c: {}, send_notification_sync=lambda a,b: {},
    )
    rt = make_mcp_tool_runtime(ctx)
    listed = rt.handle_rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {t["name"] for t in listed["result"]["tools"]}
    assert "custom.hello_foundry" in names


def test_publish_refuses_when_declared_tests_fail(monkeypatch, tmp_path):
    """A capability nobody proved must not become callable.

    Confirmed by dogfooding the core/build-capability skill against a live
    server: a project whose tests could not pass came back ok=false and never
    entered the catalogue. The happy path above proves publish CAN work; this
    pins that it refuses -- the property that makes the required `tests` array
    in the manifest mean anything.
    """
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    import arena.mcp.custom_tools as C
    C._reset_cache()
    projects.create("fib", [{"path": F.DEFAULT_MANIFEST,
                             "content": json.dumps(_manifest("fib_broken"))}],
                    overwrite=True)
    # The project runs, but produces output the declared test does not accept.
    monkeypatch.setattr(F.projects, "run",
                        lambda name, **kwargs: {"ok": True, "stdout": "FIB=999\n",
                                                "artifacts": [{"path": "out/result.json",
                                                               "text": "999"}]})

    out = F.publish("fib")

    assert out["ok"] is False
    assert not any(t["name"] == "custom.fib_broken" for t in C.list_tools())


def test_publish_run_tests_false_is_the_only_door_around_the_gate(monkeypatch, tmp_path):
    """`run_tests=False` skips the gate deliberately -- and is the only way past.

    Pinned so the escape hatch stays explicit: the same project publish rejects
    with tests enabled goes through when the caller opts out. If publish ever
    starts letting failing projects through by default, these two disagree and
    the suite says so.
    """
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    import arena.mcp.custom_tools as C
    C._reset_cache()
    projects.create("fib", [{"path": F.DEFAULT_MANIFEST,
                             "content": json.dumps(_manifest("fib_skipped"))}],
                    overwrite=True)
    monkeypatch.setattr(F.projects, "run",
                        lambda name, **kwargs: {"ok": True, "stdout": "FIB=999\n",
                                                "artifacts": []})

    assert F.publish("fib")["ok"] is False                      # gate holds
    out = F.publish("fib", run_tests=False)                     # opt out
    assert out["ok"] is True
    assert any(t["name"] == "custom.fib_skipped" for t in C.list_tools())
