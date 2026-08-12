"""Runtime helpers for browser chat extension execution."""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from arena.autonomy import is_yolo as _yolo_is_enabled
from arena.extension_bridge.instructions import extension_instructions
from arena.extension_bridge.policy import classify_tool_risk, extension_policy_snapshot


@dataclass(frozen=True)
class ExtensionBridgeRuntimeContext:
    call_tool: Callable[[str, dict[str, Any]], dict[str, Any]]
    audit: Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class ExtensionBridgeRuntime:
    policies_sync: Callable[[dict[str, Any] | None], dict[str, Any]]
    preview_sync: Callable[[dict[str, Any]], dict[str, Any]]
    execute_sync: Callable[[dict[str, Any]], dict[str, Any]]
    instructions_sync: Callable[[dict[str, Any] | None], dict[str, Any]]



def _normalize_call_tool_result(result: dict[str, Any]) -> dict[str, Any]:
    text = ""
    if isinstance(result, dict):
        parts = list(result.get("content") or [])
        if parts:
            text = str(parts[0].get("text", "") or "")
    if text:
        try:
            parsed = json.loads(text)
            return {"text": text, "parsed": parsed}
        except Exception:
            return {"text": text}
    return {"raw": result}



def make_extension_bridge_runtime(ctx: ExtensionBridgeRuntimeContext) -> ExtensionBridgeRuntime:
    def policies_sync(site: dict[str, Any] | None = None) -> dict[str, Any]:
        return extension_policy_snapshot(site)

    def instructions_sync(data: dict[str, Any] | None = None) -> dict[str, Any]:
        # v4.51.1: thread optional `category` so the popup can
        # request a full tool catalog scoped to a topic.
        data = data or {}
        return extension_instructions(
            str(data.get("format", "arena")),
            str(data.get("style", "full")),
            str(data.get("category", "")),
        )

    def preview_sync(data: dict[str, Any]) -> dict[str, Any]:
        payload = data.get("payload")
        if not isinstance(payload, dict):
            return {"ok": False, "error": "missing payload object", "status": 400}
        if str(payload.get("bridge", "") or "arena") != "arena":
            return {"ok": False, "error": "unsupported bridge payload", "status": 400}
        calls = payload.get("calls")
        if not isinstance(calls, list) or not calls:
            return {"ok": False, "error": "payload.calls must be a non-empty list", "status": 400}
        if len(calls) > 20:
            return {"ok": False, "error": "payload.calls exceeds max batch size 20", "status": 400}
        policy = extension_policy_snapshot(data.get("site") or {})
        raw_site = policy.get("site")
        site_dict: dict[str, Any] = raw_site if isinstance(raw_site, dict) else {}
        prepared = []
        requires_approval = False
        for idx, call in enumerate(calls, start=1):
            if not isinstance(call, dict):
                return {"ok": False, "error": f"call #{idx} must be an object", "status": 400}
            tool = str(call.get("tool", "") or "").strip()
            if not tool:
                return {"ok": False, "error": f"call #{idx} missing tool", "status": 400}
            arguments = call.get("arguments") or {}
            if not isinstance(arguments, dict):
                return {"ok": False, "error": f"call #{idx} arguments must be an object", "status": 400}
            risk = classify_tool_risk(tool)
            call_requires_approval = risk != "safe" or not bool(site_dict.get("trusted", False))
            requires_approval = requires_approval or call_requires_approval
            prepared.append({
                "id": str(call.get("id", "") or f"call_{idx}"),
                "tool": tool,
                "arguments": arguments,
                "risk": risk,
                "requires_approval": call_requires_approval,
            })
        return {
            "ok": True,
            "site": site_dict,
            "policy": {
                "requires_approval": requires_approval,
                "can_auto_run": not requires_approval,
            },
            "payload": {"version": int(payload.get("version", 1) or 1), "call_count": len(prepared)},
            "calls": prepared,
        }

    def execute_sync(data: dict[str, Any] | None = None) -> dict[str, Any]:
        data = data or {}
        preview = preview_sync(data)
        if not isinstance(preview, dict):
            return {"ok": False, "error": "preview failed"}
        if not preview.get("ok"):
            return preview
        raw_mode = data.get("mode")
        mode: dict[str, Any] = dict(raw_mode) if isinstance(raw_mode, dict) else {}
        approved = bool(mode.get("approve", False))
        # v4.97.0: YOLO auto-approves every tool (no human in the loop). The
        # full agent stop is enforced earlier, in the tool dispatcher's
        # call_tool chokepoint (arena.control), so HALT always wins over YOLO.
        yolo_auto = False
        if not approved and _yolo_is_enabled():
            approved = True
            yolo_auto = True
        dry_run = bool(mode.get("dry_run", False))
        raw_policy = preview.get("policy")
        policy: dict[str, Any] = dict(raw_policy) if isinstance(raw_policy, dict) else {}
        if policy.get("requires_approval") and not approved:
            return {"ok": False, "error": "approval required", "status": 403, "preview": preview}
        if dry_run:
            return {"ok": True, "dry_run": True, "preview": preview, "calls": []}
        executed = []
        all_ok = True
        raw_calls = preview.get("calls")
        calls_list: list[dict[str, Any]] = [dict(c) for c in raw_calls] if isinstance(raw_calls, list) else []
        for call in calls_list:
            raw_args = call.get("arguments")
            call_args: dict[str, Any] = dict(raw_args) if isinstance(raw_args, dict) else {}
            raw = ctx.call_tool(str(call.get("tool", "")), call_args)
            result = _normalize_call_tool_result(raw)
            parsed = result.get("parsed") if (isinstance(result, dict) and isinstance(result.get("parsed"), dict)) else {}
            raw_err = raw.get("isError", False) if isinstance(raw, dict) else False
            parsed_ok = parsed.get("ok") if isinstance(parsed, dict) else True
            ok = not bool(raw_err) and (parsed_ok is not False)
            executed.append({
                "id": call.get("id"), "tool": call.get("tool"), "ok": ok, "risk": call.get("risk"), "result": result,
            })
            all_ok = all_ok and ok
        raw_site = preview.get("site")
        site: dict[str, Any] = dict(raw_site) if isinstance(raw_site, dict) else {}
        ctx.audit({
            "type": "extension_execute",
            "site": site.get("origin", ""),
            "host": site.get("host", ""),
            "adapter": site.get("adapter", ""),
            "calls": [{"tool": item["tool"], "ok": item["ok"], "risk": item["risk"]} for item in executed],
            "approved": approved,
            "yolo_auto": yolo_auto,
            "dry_run": dry_run,
            "ok": all_ok,
        })
        return {
            "ok": all_ok,
            "executed": executed,
            "site": site,
            "approved": approved,
            "yolo_auto": yolo_auto,
            "dry_run": dry_run,
            "preview": preview,
            "calls": executed,
            "summary": f"{len(executed)} call(s) executed",
        }

    return ExtensionBridgeRuntime(policies_sync=policies_sync, preview_sync=preview_sync, execute_sync=execute_sync, instructions_sync=instructions_sync)


__all__ = ["ExtensionBridgeRuntime", "ExtensionBridgeRuntimeContext", "make_extension_bridge_runtime"]

