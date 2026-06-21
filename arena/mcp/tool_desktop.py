"""MCP desktop OCR tools via local bridge endpoints."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from arena.mcp.tool_utils import text_content



def _bridge_call(ctx, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    cfg = ctx.app_config() or {}
    port = int(cfg.get("port", 8765) or 8765)
    token = cfg.get("token", "")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _bridge_get(ctx, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = ctx.app_config() or {}
    port = int(cfg.get("port", 8765) or 8765)
    token = cfg.get("token", "")
    query = ""
    if params:
        clean = {k: v for k, v in params.items() if v not in (None, "")}
        if clean:
            query = "?" + urllib.parse.urlencode(clean)
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}{query}",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))



def handle_desktop_tool(name: str, args: dict[str, Any], *, ctx) -> dict[str, Any] | None:
    if name == "desktop.displays":
        return text_content(json.dumps(_bridge_get(ctx, "/v1/desktop/displays"), ensure_ascii=False))
    if name == "desktop.windows":
        return text_content(json.dumps(_bridge_get(ctx, "/v1/desktop/windows", args), ensure_ascii=False))
    if name == "desktop.focus":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/desktop/focus", args), ensure_ascii=False))
    if name == "desktop.window_action":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/desktop/window_action", args), ensure_ascii=False))
    if name == "desktop.resolve_text_target":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/desktop/resolve_text_target", args), ensure_ascii=False))
    if name == "desktop.ocr":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/desktop/ocr", args), ensure_ascii=False))
    if name == "desktop.find_text":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/desktop/find_text", args), ensure_ascii=False))
    if name == "desktop.click_text":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/desktop/click_text", args), ensure_ascii=False))
    return None
