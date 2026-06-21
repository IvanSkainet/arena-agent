"""Agentic runtime, handlers, and MCP regressions."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from aiohttp.test_utils import make_mocked_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.agentic.handlers import make_agentic_handlers  # noqa: E402
from arena.agentic.runtime import AgenticRuntimeContext, make_agentic_runtime  # noqa: E402
from arena.handler_context import AgenticHandlerContext  # noqa: E402
from arena.mcp.tool_agentic import handle_agentic_tool  # noqa: E402
from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402
from arena.planner.logic import build_plan  # noqa: E402
import unified_bridge as ub  # noqa: E402


def _runtime():
    return make_agentic_runtime(
        AgenticRuntimeContext(
            build_plan=build_plan,
            recall_sync=lambda query, top, profile=None: {"ok": True, "query": query, "count": 1, "facts": [{"fact": {"key": "k", "value": "v", "profile": profile or "default"}, "score": 1.0}]},
            common_status=lambda cfg: {"ok": True, "service": "arena-unified-bridge", "profile": cfg.get("profile", "owner-shell")},
            app_config=lambda: {"token": "t", "root": "/tmp", "profile": "owner-shell", "active_exec": 0, "max_concurrent": 3},
            doctor_sync=lambda token: {"ok": True, "passed": 10, "total": 10},
            sysinfo_sync=lambda root: {"ok": True, "root": str(root)},
            tasks_list_sync=lambda status, limit: {"ok": True, "count": 0, "tasks": []},
            file_watch_list_sync=lambda: {"ok": True, "count": 0, "watchers": []},
            browser_head_sync=lambda url: {"ok": True, "url": url, "status_code": 200},
        )
    )


def test_agentic_runtime_react_and_reflect():
    runtime = _runtime()
    react = runtime.react_sync(goal="Investigate a browser issue", url="https://example.com")
    assert react["ok"] is True
    assert react["iterations"]
    assert react["plan"]["suggested_memory_profile"] == "browser"
    reflect = runtime.reflect_sync(goal="Investigate a browser issue", run=react, outcome="partial")
    assert reflect["ok"] is True
    assert reflect["confidence"] in {"medium", "high"}



def test_agentic_handlers_routes_shape():
    runtime = _runtime()
    audit = []
    handlers = make_agentic_handlers(
        AgenticHandlerContext(
            require_auth=lambda request: None,
            record_request=lambda *args, **kwargs: None,
            cors_json_response=ub._cors_json_response,
            react_sync=runtime.react_sync,
            reflect_sync=runtime.reflect_sync,
            audit=audit.append,
        )
    )
    react_req = make_mocked_request("POST", "/v1/react", headers={"Authorization": "Bearer t"})
    async def _react_json():
        return {"goal": "Check browser state", "url": "https://example.com"}
    react_req.json = _react_json
    react_resp = asyncio.run(handlers.react(react_req))
    react_data = json.loads(react_resp.text)
    assert react_data["ok"] is True
    assert audit and audit[0]["event"] == "react_run"

    reflect_req = make_mocked_request("POST", "/v1/reflect", headers={"Authorization": "Bearer t"})
    async def _reflect_json():
        return {"goal": "Check browser state", "run": react_data, "outcome": "ok"}
    reflect_req.json = _reflect_json
    reflect_resp = asyncio.run(handlers.reflect(reflect_req))
    reflect_data = json.loads(reflect_resp.text)
    assert reflect_data["ok"] is True



def test_agentic_mcp_tools_and_registry():
    runtime = _runtime()
    ctx = type("Ctx", (), {"react_sync": staticmethod(runtime.react_sync), "reflect_sync": staticmethod(runtime.reflect_sync)})()
    react = handle_agentic_tool("react.run", {"goal": "Inspect a desktop issue"}, ctx=ctx)
    reflect = handle_agentic_tool("reflect.run", {"goal": "Inspect a desktop issue", "run": json.loads(react["content"][0]["text"]), "outcome": "pending"}, ctx=ctx)
    assert json.loads(react["content"][0]["text"])["ok"] is True
    assert json.loads(reflect["content"][0]["text"])["ok"] is True
    names = [tool["name"] for tool in MCP_TOOLS]
    assert "react.run" in names
    assert "reflect.run" in names


def test_agentic_routes_registered():
    app = ub.make_app({"token": "test"})
    paths = {(r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter")) for r in app.router.routes()}
    assert ("POST", "/v1/react") in paths
    assert ("POST", "/v1/reflect") in paths
