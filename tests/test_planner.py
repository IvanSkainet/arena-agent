"""Planner logic, handler, and MCP regressions."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from aiohttp.test_utils import make_mocked_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.handler_context import PlannerHandlerContext  # noqa: E402
from arena.mcp.tool_plan import handle_plan_tool  # noqa: E402
from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402
from arena.planner.handlers import make_planner_handlers  # noqa: E402
from arena.planner.logic import build_plan, infer_memory_profile  # noqa: E402
import unified_bridge as ub  # noqa: E402


def test_infer_memory_profile_heuristics():
    assert infer_memory_profile("fix a bug in my repo") == "code"
    assert infer_memory_profile("search the web for docs") == "browser"
    assert infer_memory_profile("remember my timezone preference") == "personal"
    assert infer_memory_profile("generic task") == "default"


def test_build_plan_returns_structured_steps():
    result = build_plan(goal="fix failing tests in project", context="repo work", max_steps=6)
    assert result["ok"] is True
    assert result["suggested_memory_profile"] == "code"
    assert result["steps"]
    assert len(result["steps"]) <= 6
    assert all("suggested_tools" in step for step in result["steps"])
    assert "git.status" in result["required_tools"]


class _Audit(list):
    def __call__(self, event):
        self.append(event)


async def _plan_request(body: dict):
    req = make_mocked_request("POST", "/v1/plan", headers={"Authorization": "Bearer t"})
    async def _json():
        return body
    req.json = _json
    return req


def test_planner_handler_success_records_audit():
    audit = _Audit()
    handlers = make_planner_handlers(
        PlannerHandlerContext(
            require_auth=lambda request: None,
            record_request=lambda *args, **kwargs: None,
            cors_json_response=ub._cors_json_response,
            build_plan=build_plan,
            audit=audit,
        )
    )
    resp = asyncio.run(handlers.plan(asyncio.run(_plan_request({"goal": "search docs on a website"}))))
    data = json.loads(resp.text)
    assert data["ok"] is True
    assert data["suggested_memory_profile"] == "browser"
    assert audit and audit[0]["event"] == "plan_created"


def test_planner_handler_requires_goal():
    handlers = make_planner_handlers(
        PlannerHandlerContext(
            require_auth=lambda request: None,
            record_request=lambda *args, **kwargs: None,
            cors_json_response=ub._cors_json_response,
            build_plan=build_plan,
            audit=lambda event: None,
        )
    )
    resp = asyncio.run(handlers.plan(asyncio.run(_plan_request({}))))
    assert resp.status == 400


def test_plan_tool_and_registry():
    ctx = type("Ctx", (), {"build_plan": staticmethod(build_plan)})()
    result = handle_plan_tool("plan.create", {"goal": "investigate a browser issue", "max_steps": 5}, ctx=ctx)
    payload = json.loads(result["content"][0]["text"])
    assert payload["ok"] is True
    assert payload["suggested_memory_profile"] == "browser"
    assert any(tool["name"] == "plan.create" for tool in MCP_TOOLS)


def test_plan_route_registered():
    app = ub.make_app({"token": "test"})
    paths = {(r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter")) for r in app.router.routes()}
    assert ("POST", "/v1/plan") in paths
