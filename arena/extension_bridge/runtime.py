"""Runtime helpers for browser chat extension execution."""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

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
            call_requires_approval = risk != "safe" or not policy["site"].get("trusted", False)
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
            "site": policy["site"],
            "policy": {
                "requires_approval": requires_approval,
                "can_auto_run": not requires_approval,
            },
            "payload": {"version": int(payload.get("version", 1) or 1), "call_count": len(prepared)},
            "calls": prepared,
        }

    def execute_sync(data: dict[str, Any]) -> dict[str, Any]:
        preview = preview_sync(data)
        if not preview.get("ok"):
            return preview
        mode = data.get("mode") if isinstance(data.get("mode"), dict) else {}
        approved = bool(mode.get("approve", False))
        dry_run = bool(mode.get("dry_run", False))
        if preview["policy"].get("requires_approval") and not approved:
            return {"ok": False, "error": "approval required", "status": 403, "preview": preview}
        if dry_run:
            return {"ok": True, "dry_run": True, "preview": preview, "calls": []}
        executed = []
        all_ok = True
        for call in preview["calls"]:
            raw = ctx.call_tool(call["tool"], call["arguments"])
            ok = not bool(raw.get("isError", False))
            executed.append({
                "id": call["id"],
                "tool": call["tool"],
                "ok": ok,
                "risk": call["risk"],
                "result": _normalize_call_tool_result(raw),
            })
            all_ok = all_ok and ok
        ctx.audit({
            "type": "extension_execute",
            "site": preview["site"].get("origin", ""),
            "host": preview["site"].get("host", ""),
            "adapter": preview["site"].get("adapter", ""),
            "calls": [{"tool": item["tool"], "ok": item["ok"], "risk": item["risk"]} for item in executed],
            "approved": approved,
            "dry_run": dry_run,
            "ok": all_ok,
        })
        return {"ok": all_ok, "site": preview["site"], "calls": executed, "summary": f"{len(executed)} call(s) executed"}

    return ExtensionBridgeRuntime(policies_sync=policies_sync, preview_sync=preview_sync, execute_sync=execute_sync)


__all__ = ["ExtensionBridgeRuntime", "ExtensionBridgeRuntimeContext", "make_extension_bridge_runtime"]
