"""Browser chat extension bridge regressions."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from aiohttp.test_utils import make_mocked_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.extension_bridge.handlers import make_extension_bridge_handlers  # noqa: E402
from arena.extension_bridge.runtime import ExtensionBridgeRuntimeContext, make_extension_bridge_runtime  # noqa: E402
from arena.handler_context import ExtensionBridgeHandlerContext  # noqa: E402



def _runtime():
    seen = []

    def _call_tool(name, args):
        seen.append((name, args))
        return {"content": [{"type": "text", "text": json.dumps({"ok": True, "tool": name, "arguments": args})}]}

    runtime = make_extension_bridge_runtime(ExtensionBridgeRuntimeContext(call_tool=_call_tool, audit=lambda event: None))
    return runtime, seen



def test_extension_preview_and_execute_runtime():
    runtime, seen = _runtime()
    payload = {
        "site": {"origin": "https://chat.openai.com", "url": "https://chat.openai.com/c/demo", "adapter": "chatgpt"},
        "payload": {"bridge": "arena", "version": 1, "calls": [{"id": "c1", "tool": "mission.family", "arguments": {"mission_id": "demo"}}]},
        "mode": {"approve": True},
    }
    preview = runtime.preview_sync(payload)
    assert preview["ok"] is True
    assert preview["policy"]["can_auto_run"] is True
    assert preview["calls"][0]["risk"] == "safe"

    execute = runtime.execute_sync(payload)
    assert execute["ok"] is True
    assert execute["calls"][0]["result"]["parsed"]["tool"] == "mission.family"
    assert seen[0][0] == "mission.family"



def test_extension_execute_requires_approval_for_dangerous_call():
    runtime, _seen = _runtime()
    payload = {
        "site": {"origin": "https://unknown.example", "url": "https://unknown.example/chat", "adapter": "generic"},
        "payload": {"bridge": "arena", "version": 1, "calls": [{"tool": "mission.run", "arguments": {"mission_id": "demo"}}]},
        "mode": {},
    }
    result = runtime.execute_sync(payload)
    assert result["ok"] is False
    assert result["status"] == 403
    assert result["preview"]["calls"][0]["risk"] == "dangerous"



def test_extension_instructions_runtime():
    runtime, _seen = _runtime()
    arena = runtime.instructions_sync({"format": "arena", "style": "full"})
    assert arena["ok"] is True
    assert "```arena-tool" in arena["text"]
    assert ("Do not invent tool results" in arena["text"]
            or "Do not invent a fake result" in arena["text"]
            or "NEVER fabricate the result yourself" in arena["text"])
    jsonl = runtime.instructions_sync({"format": "jsonl", "style": "full"})
    assert "```jsonl" in jsonl["text"]
    assert "function_call_start" in jsonl["text"]


def test_extension_handlers_and_routes():
    runtime, _seen = _runtime()
    ctx = ExtensionBridgeHandlerContext(
        require_auth=lambda request: None,
        record_request=lambda *args, **kwargs: None,
        cors_json_response=ub._cors_json_response,
        executor=ub._EXECUTOR,
        policies_sync=runtime.policies_sync,
        preview_sync=runtime.preview_sync,
        execute_sync=runtime.execute_sync,
        instructions_sync=runtime.instructions_sync,
    )
    handlers = make_extension_bridge_handlers(ctx)

    policies_req = make_mocked_request("GET", "/v1/extension/policies", headers={"Authorization": "Bearer t"})
    policies_resp = asyncio.run(handlers.policies(policies_req))
    policies_data = json.loads(policies_resp.text)
    assert policies_data["ok"] is True

    preview_req = make_mocked_request("POST", "/v1/extension/preview", headers={"Authorization": "Bearer t"})

    async def _preview_json():
        return {"site": {"origin": "https://chat.openai.com"}, "payload": {"bridge": "arena", "version": 1, "calls": [{"tool": "mission.lineage", "arguments": {"mission_id": "demo"}}]}}

    preview_req.json = _preview_json
    preview_resp = asyncio.run(handlers.preview(preview_req))
    preview_data = json.loads(preview_resp.text)
    assert preview_data["ok"] is True
    assert preview_data["calls"][0]["tool"] == "mission.lineage"

    execute_req = make_mocked_request("POST", "/v1/extension/execute", headers={"Authorization": "Bearer t"})

    async def _execute_json():
        return {"site": {"origin": "https://chat.openai.com"}, "payload": {"bridge": "arena", "version": 1, "calls": [{"tool": "mission.lineage", "arguments": {"mission_id": "demo"}}]}, "mode": {"approve": True}}

    execute_req.json = _execute_json
    execute_resp = asyncio.run(handlers.execute(execute_req))
    execute_data = json.loads(execute_resp.text)
    assert execute_data["ok"] is True

    runtime_fail = make_extension_bridge_runtime(ExtensionBridgeRuntimeContext(
        call_tool=lambda name, args: {"content": [{"type": "text", "text": json.dumps({"ok": False, "error": "missing", "status": 404})}]},
        audit=lambda item: None,
    ))
    failed = runtime_fail.execute_sync({"site": {"origin": "https://chat.openai.com"}, "payload": {"bridge": "arena", "version": 1, "calls": [{"tool": "mission.lineage", "arguments": {"mission_id": "demo"}}]}, "mode": {"approve": True}})
    assert failed["ok"] is False
    assert failed["calls"][0]["result"]["parsed"]["error"] == "missing"

    app = ub.make_app({"token": "test"})
    paths = {(r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter")) for r in app.router.routes()}
    assert ("GET", "/v1/extension/policies") in paths
    assert ("GET", "/v1/extension/instructions") in paths
    assert ("POST", "/v1/extension/preview") in paths
    assert ("POST", "/v1/extension/execute") in paths
