"""MCP mission composition tools via local bridge endpoints."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, cast
from urllib.parse import quote, urlencode

from arena import mission_autopilot as _autopilot
from arena.mcp.tool_utils import text_content


def _bridge_call(ctx, path: str, payload: dict[str, Any] | None = None, *, method: str = "POST") -> dict[str, Any]:
    cfg = ctx.app_config() or {}
    port = int(cfg.get("port", 8765) or 8765)
    token = cfg.get("token", "")
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # nosec B310 -- loopback bridge URL for local MCP tool  # nosemgrep: dynamic-urllib-use-detected -- URL either loopback / fixed internal endpoint OR routed through arena.security_ssrf._validate_url (see bandit B310 nosec on the same line for the specific rationale)
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = None
        # json.loads happily returns a list, str or number; only a mapping can
        # take the setdefault calls below.
        if not isinstance(parsed, dict):
            parsed = {"ok": False, "error": body or str(e)}
        # Values are mixed (bool/str/int status); without this the inferred
        # value type from the literal above rejects the int below.
        parsed = cast("dict[str, Any]", parsed)
        parsed.setdefault("ok", False)
        parsed.setdefault("status", e.code)
        parsed.setdefault("error", str(e))
        return parsed



def handle_mission_tool(name: str, args: dict[str, Any], *, ctx) -> dict[str, Any] | None:
    cfg = ctx.app_config() or {}
    port = int(cfg.get("port", 8765) or 8765)
    token = str(cfg.get("token", "") or "")
    if name == "mission.autopilot_start":
        return text_content(json.dumps(_autopilot.start(
            goal=str(args.get("goal") or ""),
            steps=args.get("steps") if isinstance(args.get("steps"), list) else None,
            constraints=args.get("constraints") if isinstance(args.get("constraints"), list) else None,
            max_steps=int(args.get("max_steps", 12) or 12),
            timeout_per_step=int(args.get("timeout_per_step", 60) or 60),
            create_record=bool(args.get("create_record", True)),
            scenario_name=str(args.get("scenario") or args.get("scenario_name") or ""),
            port=port,
            token=token,
        ), ensure_ascii=False))
    if name == "mission.autopilot_status":
        return text_content(json.dumps(_autopilot.status(str(args.get("run_id") or "")), ensure_ascii=False))
    if name == "mission.autopilot_report":
        return text_content(json.dumps(_autopilot.report(str(args.get("run_id") or "")), ensure_ascii=False))
    if name == "mission.autopilot_list":
        return text_content(json.dumps(_autopilot.list_runs(int(args.get("limit", 20) or 20)), ensure_ascii=False))
    if name == "mission.autopilot_cancel":
        return text_content(json.dumps(_autopilot.cancel(str(args.get("run_id") or "")), ensure_ascii=False))
    if name == "mission.autopilot_step":
        return text_content(json.dumps(_autopilot.step(
            run_id=str(args.get("run_id") or ""),
            tool=str(args.get("tool") or ""),
            arguments=args.get("arguments") if isinstance(args.get("arguments"), dict) else None,
            step_id=str(args.get("step_id") or ""),
            timeout=int(args.get("timeout", 60) or 60),
            port=port,
            token=token,
        ), ensure_ascii=False))
    if name == "mission.autopilot_artifacts":
        return text_content(json.dumps(_autopilot.artifacts(str(args.get("run_id") or "")), ensure_ascii=False))
    if name == "mission.autopilot_from_goal":
        return text_content(json.dumps(_autopilot.from_goal(
            goal=str(args.get("goal") or ""),
            constraints=args.get("constraints") if isinstance(args.get("constraints"), list) else None,
            max_steps=int(args.get("max_steps", 12) or 12),
            timeout_per_step=int(args.get("timeout_per_step", 60) or 60),
            create_record=bool(args.get("create_record", True)),
            scenario_name=str(args.get("scenario") or args.get("scenario_name") or ""),
            port=port,
            token=token,
        ), ensure_ascii=False))
    if name == "mission.autopilot_start_async":
        return text_content(json.dumps(_autopilot.start_async(
            goal=str(args.get("goal") or ""),
            steps=args.get("steps") if isinstance(args.get("steps"), list) else None,
            constraints=args.get("constraints") if isinstance(args.get("constraints"), list) else None,
            max_steps=int(args.get("max_steps", 12) or 12),
            timeout_per_step=int(args.get("timeout_per_step", 60) or 60),
            create_record=bool(args.get("create_record", True)),
            scenario_name=str(args.get("scenario") or args.get("scenario_name") or ""),
            port=port,
            token=token,
        ), ensure_ascii=False))
    if name == "mission.control_status":
        from arena import mission_control as _mc
        return text_content(json.dumps(_mc.control_status(port=port, token=token), ensure_ascii=False))

    mission_name = quote(str(args.get("mission_id", "") or args.get("name", "")), safe="")
    if name == "mission.templates":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/mission/templates", None, method="GET"), ensure_ascii=False))
    if name == "mission.status":
        return text_content(json.dumps(_bridge_call(ctx, f"/v1/mission/status?name={mission_name}", None, method="GET"), ensure_ascii=False))
    if name == "mission.report":
        return text_content(json.dumps(_bridge_call(ctx, f"/v1/mission/report?name={mission_name}", None, method="GET"), ensure_ascii=False))
    if name == "mission.history":
        return text_content(json.dumps(_bridge_call(ctx, f"/v1/mission/history?name={mission_name}", None, method="GET"), ensure_ascii=False))
    if name == "mission.lineage":
        return text_content(json.dumps(_bridge_call(ctx, f"/v1/mission/lineage?name={mission_name}", None, method="GET"), ensure_ascii=False))
    if name == "mission.family":
        return text_content(json.dumps(_bridge_call(ctx, f"/v1/mission/family?name={mission_name}", None, method="GET"), ensure_ascii=False))
    if name == "mission.catalog":
        query = urlencode({k: v for k, v in {"q": args.get("query", "") or args.get("q", ""), "state": args.get("state", ""), "template": args.get("template", ""), "has_report": args.get("has_report"), "limit": args.get("limit"), "offset": args.get("offset")}.items() if v not in (None, "")})
        suffix = f"?{query}" if query else ""
        return text_content(json.dumps(_bridge_call(ctx, f"/v1/mission/catalog{suffix}", None, method="GET"), ensure_ascii=False))
    if name == "mission.compose":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/mission/compose", args), ensure_ascii=False))
    if name == "mission.create":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/mission/create", args), ensure_ascii=False))
    if name == "mission.propose":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/mission/propose", args), ensure_ascii=False))
    if name == "mission.run":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/mission/run", args), ensure_ascii=False))
    if name == "mission.rerun":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/mission/rerun", args), ensure_ascii=False))
    if name == "mission.recover":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/mission/recover", args), ensure_ascii=False))
    if name == "mission.followup":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/mission/followup", args), ensure_ascii=False))
    if name == "mission.iterate":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/mission/iterate", args), ensure_ascii=False))
    if name == "mission.schedules":
        query = urlencode({k: v for k, v in {"action": args.get("action", ""), "enabled": args.get("enabled"), "due_only": args.get("due_only"), "limit": args.get("limit")}.items() if v not in (None, "")})
        suffix = f"?{query}" if query else ""
        return text_content(json.dumps(_bridge_call(ctx, f"/v1/mission/schedules{suffix}", None, method="GET"), ensure_ascii=False))
    if name == "mission.schedule_state":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/mission/schedules/state", None, method="GET"), ensure_ascii=False))
    if name == "mission.schedule_save":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/mission/schedules", args), ensure_ascii=False))
    if name == "mission.schedule_delete":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/mission/schedules", args, method="DELETE"), ensure_ascii=False))
    if name == "mission.schedule_tick":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/mission/schedules/tick", args), ensure_ascii=False))
    return None
