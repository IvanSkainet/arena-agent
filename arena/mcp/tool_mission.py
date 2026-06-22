"""MCP mission composition tools via local bridge endpoints."""
from __future__ import annotations

import json
import urllib.request
from typing import Any

from arena.mcp.tool_utils import text_content


def _bridge_call(ctx, path: str, payload: dict[str, Any] | None = None, *, method: str = "POST") -> dict[str, Any]:
    cfg = ctx.app_config() or {}
    port = int(cfg.get("port", 8765) or 8765)
    token = cfg.get("token", "")
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))



def handle_mission_tool(name: str, args: dict[str, Any], *, ctx) -> dict[str, Any] | None:
    if name == "mission.templates":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/mission/templates", None, method="GET"), ensure_ascii=False))
    if name == "mission.status":
        return text_content(json.dumps(_bridge_call(ctx, f"/v1/mission/status?name={args.get('mission_id','') or args.get('name','')}", None, method="GET"), ensure_ascii=False))
    if name == "mission.report":
        return text_content(json.dumps(_bridge_call(ctx, f"/v1/mission/report?name={args.get('mission_id','') or args.get('name','')}", None, method="GET"), ensure_ascii=False))
    if name == "mission.compose":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/mission/compose", args), ensure_ascii=False))
    if name == "mission.create":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/mission/create", args), ensure_ascii=False))
    if name == "mission.propose":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/mission/propose", args), ensure_ascii=False))
    if name == "mission.run":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/mission/run", args), ensure_ascii=False))
    return None
